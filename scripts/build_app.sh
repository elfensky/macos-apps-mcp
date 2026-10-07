#!/bin/bash
# Build macos-apps-mcp.app — hand-rolled (spec fork resolution), universal2
# (arm64 + x86_64). Layout puts the python-build-standalone interpreter at
# Contents/MacOS/<exe> and the stdlib at Contents/lib/python3.14 so CPython's
# getpath finds prefix relative to the executable — NO PYTHONHOME/PYTHONPATH env
# needed by launchd or client configs.
# Signing is INSIDE-OUT per Mach-O with --timestamp --options runtime; no recursive
# signing. codesign signs (and --verify checks) every slice of a fat file.
set -euo pipefail

SIGN="" NOTARIZE="" OUT="dist"
while [[ $# -gt 0 ]]; do case "$1" in
  --sign) SIGN="$2"; shift 2;;
  --notarize) NOTARIZE="$2"; shift 2;;
  --out) OUT="$2"; shift 2;;
  *) echo "unknown arg $1" >&2; exit 2;;
esac; done

[[ -n "$NOTARIZE" && -z "$SIGN" ]] && { echo "--notarize requires --sign" >&2; exit 2; }
# Preflight: both slices are smoke-run here (x86_64 under Rosetta), and lipo/vtool
# come from the Xcode Command Line Tools — fail now, not after the installs.
{ /usr/bin/arch -arm64 /usr/bin/true && /usr/bin/arch -x86_64 /usr/bin/true \
    && xcrun -f vtool >/dev/null; } 2>/dev/null \
  || { echo "build needs an Apple-silicon Mac with Rosetta 2 (softwareupdate" \
       "--install-rosetta --agree-to-license) and the Xcode Command Line Tools" >&2
       exit 2; }

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PYVER=3.14
# The floor's single source is packaging/Info.plist; it sets the wheel tags uv
# may pick and the minos gate below.
MACOS_MIN="$(plutil -extract LSMinimumSystemVersion raw "$REPO/packaging/Info.plist")"
# Pinned interpreter: the SAME python-build-standalone release for both arches
# (0.14.1 shipped 20260510). A uv-managed glob can pick x86_64 or a newer sqlite.
PBS_TAG=20260510 PBS_PY=3.14.5
PBS_SHA_aarch64=1bb0b3d45448dfe7e916dc62144cfd7d7a611dc6ccf05b8bb71662cc5c2a1ad2
PBS_SHA_x86_64=38662e526797db4e90b3381706b96821979fece0b536ac14b5c4e1a97e0590d5
CACHE="${PBS_CACHE:-$HOME/Library/Caches/macos-apps-mcp-build}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
APP="$OUT/macos-apps-mcp.app"
is_macho() { file -b "$1" | grep -q '^Mach-O'; }
lipo2() { lipo -create "$1" "$2" -output "$WORK/fat" && mv "$WORK/fat" "$1"; }

# 1. universal2 interpreter: lipo the two thin PBS builds over the arm64 tree.
mkdir -p "$CACHE"
for a in aarch64 x86_64; do
  t="cpython-$PBS_PY+$PBS_TAG-$a-apple-darwin-install_only_stripped.tar.gz"
  if [[ ! -f "$CACHE/$t" ]]; then   # .part, then mv: a cut download never sits in the cache
    curl -fsSL -o "$CACHE/$t.part" \
      "https://github.com/astral-sh/python-build-standalone/releases/download/$PBS_TAG/${t//+/%2B}"
    mv "$CACHE/$t.part" "$CACHE/$t"
  fi
  sha="PBS_SHA_$a"
  echo "${!sha}  $CACHE/$t" | shasum -a 256 -c - >/dev/null 2>&1 \
    || { echo "PBS SHA256 MISMATCH ($a): $CACHE/$t — delete it and rebuild" >&2; exit 1; }
  mkdir -p "$WORK/$a" && tar -xzf "$CACHE/$t" -C "$WORK/$a"
done
STD="$WORK/aarch64/python" X="$WORK/x86_64/python"
(cd "$STD" && find "bin/python$PYVER" "lib/python$PYVER" -type f -print0) |
  while IFS= read -r -d '' f; do
  if is_macho "$STD/$f"; then lipo2 "$STD/$f" "$X/$f"; fi
done

rm -rf "$APP"; mkdir -p "$APP/Contents/MacOS" "$APP/Contents/lib" \
  "$APP/Contents/Library/LaunchAgents" "$APP/Contents/Resources"
cp "$STD/bin/python${PYVER}" "$APP/Contents/MacOS/macos-apps-mcp"   # real file (codesign)
cp -R "$STD/lib/python${PYVER}" "$APP/Contents/lib/python${PYVER}"  # stdlib for getpath
SITE="$APP/Contents/lib/python${PYVER}/site-packages"

# 2. Locked deps (#286), one tree per arch, then lipo the thin .so files.
# cryptography (+cffi, pycparser) is reached only via mcp's pyjwt[crypto] and
# fastmcp's auth modules; no auth is configured, so the bundle never imports it,
# and 49+ has no x86_64 wheel (#205). --prune drops it from the export; --no-deps
# stops uv re-resolving it unpinned from PyPI. --no-build: a cross-arch sdist
# build would compile for the HOST arch. MACOSX_DEPLOYMENT_TARGET applies only
# with --python-platform (else uv takes the build host's macOS tags).
uv export --project "$REPO" --frozen --no-dev --no-emit-project \
  --prune cryptography > "$WORK/reqs"
for a in aarch64 x86_64; do
  MACOSX_DEPLOYMENT_TARGET="$MACOS_MIN" uv pip install -q \
    --python "$STD/bin/python${PYVER}" --python-platform "$a-apple-darwin" \
    --python-version "$PYVER" --no-build --no-deps --require-hashes \
    --target "$WORK/site-$a" -r "$WORK/reqs"
done
diff <(cd "$WORK/site-aarch64" && find . | sort) \
  <(cd "$WORK/site-x86_64" && find . | sort) >&2 \
  || { echo "ARCH TREES DIFFER: per-arch wheels ship different files"; exit 1; }
ditto "$WORK/site-aarch64" "$SITE"
(cd "$WORK/site-aarch64" && find . -type f -print0) | while IFS= read -r -d '' f; do
  cmp -s "$SITE/$f" "$WORK/site-x86_64/$f" && continue   # pure, or already universal2
  if is_macho "$SITE/$f"; then lipo2 "$SITE/$f" "$WORK/site-x86_64/$f"
  elif [[ "$f" != *.dist-info/* ]]; then echo "ARCH-SPECIFIC NON-BINARY: $f"; exit 1; fi
done
uv pip install -q --python "$STD/bin/python${PYVER}" --target "$SITE" --no-deps "$REPO"
# Build stamp (#143): doctor().build reports which BUILD serves a call — version
# alone cannot see a same-version rebuild. describe --dirty so an uncommitted-tree
# build cannot masquerade as its commit.
printf '%s %s\n' "$(git -C "$REPO" describe --always --dirty --exclude '*')" \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$SITE/macos_apps_mcp/build_stamp"
sed "s|__APP__|/Applications/macos-apps-mcp.app|" \
  "$REPO/packaging/ren.lav.macos-apps-mcp.plist" \
  > "$APP/Contents/Library/LaunchAgents/ren.lav.macos-apps-mcp.plist"
cp "$REPO/packaging/Info.plist" "$APP/Contents/Info.plist"

# Gate: every Mach-O is universal2 and no slice needs a newer macOS than MACOS_MIN.
# Before the smokes, so a thin or too-new extension is named here, not as a smoke
# failure. compileall adds no Mach-O.
find "$APP" -type f -print0 | while IFS= read -r -d '' f; do
  is_macho "$f" || continue
  [[ "$(lipo -archs "$f")" == "x86_64 arm64" ]] || { echo "NOT UNIVERSAL2: $f"; exit 1; }
  for a in arm64 x86_64; do
    m="$(vtool -arch "$a" -show-build "$f" | awk '$1=="minos"||$1=="version"{print $2; exit}')"
    [[ -n "$m" && "$(printf '%s\n' "$m" "$MACOS_MIN" | sort -V | tail -1)" == "$MACOS_MIN" ]] \
      || { echo "MINOS ${m:-?} > $MACOS_MIN ($a): $f"; exit 1; }
  done
done
echo "universal2 gate ok: every Mach-O is x86_64 arm64, minos <= $MACOS_MIN"

# Smokes on BOTH slices (x86_64 runs under Rosetta: `softwareupdate --install-rosetta`).
for a in arm64 x86_64; do
  env -i /usr/bin/arch "-$a" "$APP/Contents/MacOS/macos-apps-mcp" -c "import macos_apps_mcp" \
    || { echo "BUNDLE SMOKE FAILED ($a): getpath layout wrong"; exit 1; }
  # one streamed tool call through the shim's transport, on the bundled libraries (#286)
  /usr/bin/arch "-$a" "$APP/Contents/MacOS/macos-apps-mcp" -E -s -P \
    "$REPO/scripts/smoke_stream.py" \
    || { echo "STREAM SMOKE FAILED ($a): bundled mcp/fastmcp break the shim (#286)"; exit 1; }
  echo "smokes ok: $a"
done
# Precompile every module BEFORE signing: otherwise the daemon writes .pyc into the
# signed Contents/lib on its first imports and breaks the seal (codesign --strict).
# .pyc is arch-neutral; one slice compiles for both.
"$APP/Contents/MacOS/macos-apps-mcp" -E -s -P -m compileall -q -j 0 \
  "$APP/Contents/lib/python${PYVER}" >/dev/null \
  || { echo "BYTECODE PRECOMPILE FAILED"; exit 1; }


if [[ -n "$SIGN" ]]; then
  ENTS="$REPO/packaging/entitlements.plist"
  EXE="$APP/Contents/MacOS/macos-apps-mcp"
  # Intel needs ONE exception, and only Intel gets it (#205, operator decision
  # 2026-10-07). libffi has no pre-built trampoline pages on x86_64 — neither PBS's
  # copy nor Apple's /usr/lib/libffi.dylib — so ctypes and PyObjC write closure code
  # at startup, which the hardened runtime refuses (hang / MemoryError). arm64 has
  # the trampoline pages and keeps the strict set. Derived, not a second file, so the
  # two sets cannot drift apart.
  ENTS_X86="$WORK/entitlements-x86_64.plist"
  cp "$ENTS" "$ENTS_X86"
  # PlistBuddy, not plutil: plutil reads the dots in the key as a key path.
  /usr/libexec/PlistBuddy -c \
    "Add :com.apple.security.cs.allow-unsigned-executable-memory bool true" "$ENTS_X86"
  # inside-out: every nested Mach-O first (libraries carry no entitlements)...
  find "$APP/Contents/lib" \( -name '*.so' -o -name '*.dylib' \) -print0 |
    while IFS= read -r -d '' f; do
      codesign --force --timestamp --options runtime -s "$SIGN" "$f"
    done
  # ...then the bundle, whose signature lives in the main executable. codesign takes
  # one entitlement set per run, so sign once per set, keep the matching slice of
  # each, and join them. Both runs seal the same resources, so both slices point at
  # the same CodeResources.
  codesign --force --timestamp --options runtime --entitlements "$ENTS_X86" \
    -s "$SIGN" "$APP"
  lipo "$EXE" -thin x86_64 -output "$WORK/exe-x86_64"
  codesign --force --timestamp --options runtime --entitlements "$ENTS" \
    -s "$SIGN" "$APP"
  lipo "$EXE" -thin arm64 -output "$WORK/exe-arm64"
  lipo -create "$WORK/exe-x86_64" "$WORK/exe-arm64" -output "$EXE"
  codesign --verify --strict --verbose=2 "$APP"
  # Gate: the exception is on the x86_64 slice and NOT on arm64.
  # (captured first: under pipefail, `codesign | grep -q` can fail on SIGPIPE)
  ex="com.apple.security.cs.allow-unsigned-executable-memory"
  e_x86="$(codesign -d --entitlements - --arch x86_64 "$EXE" 2>/dev/null)"
  e_arm="$(codesign -d --entitlements - --arch arm64 "$EXE" 2>/dev/null)"
  [[ "$e_x86" == *"$ex"* ]] || { echo "ENTITLEMENTS: x86_64 slice lacks $ex"; exit 1; }
  [[ "$e_arm" != *"$ex"* && "$e_arm" == *apple-events* ]] \
    || { echo "ENTITLEMENTS: arm64 slice is not the strict set"; exit 1; }
  echo "entitlements ok: x86_64 has the exception, arm64 is strict"
  # The smokes above ran unsigned; the hardened runtime can still break a slice. The
  # failure is a hang with TMPDIR set (as under launchd), so keep the env, cap the
  # time. The server import pulls PyObjC; the CFUNCTYPE is a real closure allocation.
  # -B: no .pyc into the sealed bundle; --verify below proves the seal held.
  for a in arm64 x86_64; do
    /usr/bin/perl -e 'alarm shift; exec @ARGV' 120 /usr/bin/arch "-$a" "$EXE" \
      -E -s -P -B -c "import ctypes, macos_apps_mcp.server
ctypes.CFUNCTYPE(None)(lambda: None)" \
      || { echo "SIGNED SMOKE FAILED ($a): the hardened runtime breaks it"; exit 1; }
    echo "signed smoke ok: $a"
  done
  codesign --verify --strict --verbose=2 "$APP"
fi

if [[ -n "$NOTARIZE" ]]; then
  ditto -c -k --keepParent "$APP" "$OUT/macos-apps-mcp.zip"
  xcrun notarytool submit "$OUT/macos-apps-mcp.zip" \
    --keychain-profile "$NOTARIZE" --wait
  xcrun stapler staple "$APP"
fi
echo "built: $APP"
