#!/bin/bash
# Build macos-apps-mcp.app — hand-rolled (spec fork resolution). Layout puts the
# python-build-standalone interpreter at Contents/MacOS/<exe> and the stdlib at
# Contents/lib/python3.14 so CPython's getpath finds prefix relative to the
# executable — NO PYTHONHOME/PYTHONPATH env needed by launchd or client configs.
# Signing is INSIDE-OUT per Mach-O with --timestamp --options runtime; no recursive signing.
set -euo pipefail

SIGN="" NOTARIZE="" OUT="dist"
while [[ $# -gt 0 ]]; do case "$1" in
  --sign) SIGN="$2"; shift 2;;
  --notarize) NOTARIZE="$2"; shift 2;;
  --out) OUT="$2"; shift 2;;
  *) echo "unknown arg $1" >&2; exit 2;;
esac; done

[[ -n "$NOTARIZE" && -z "$SIGN" ]] && { echo "--notarize requires --sign" >&2; exit 2; }

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PYVER=3.14
STD="$(ls -d "$HOME"/.local/share/uv/python/cpython-${PYVER}*-macos-*/ | sort -V | tail -1)"
APP="$OUT/macos-apps-mcp.app"
rm -rf "$APP"; mkdir -p "$APP/Contents/MacOS" "$APP/Contents/lib" \
  "$APP/Contents/Library/LaunchAgents" "$APP/Contents/Resources"

cp "$STD/bin/python${PYVER}" "$APP/Contents/MacOS/macos-apps-mcp"   # real file (codesign)
cp -R "$STD/lib/python${PYVER}" "$APP/Contents/lib/python${PYVER}"  # stdlib for getpath
SITE="$APP/Contents/lib/python${PYVER}/site-packages"
uv pip install --python "$STD/bin/python${PYVER}" --target "$SITE" "$REPO"
# Build stamp (#143): doctor().build reports which BUILD serves a call — version
# alone cannot see a same-version rebuild. describe --dirty so an uncommitted-tree
# build cannot masquerade as its commit.
printf '%s %s\n' "$(git -C "$REPO" describe --always --dirty)" \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$SITE/macos_apps_mcp/build_stamp"
sed "s|__APP__|/Applications/macos-apps-mcp.app|" \
  "$REPO/packaging/ren.lav.macos-apps-mcp.plist" \
  > "$APP/Contents/Library/LaunchAgents/ren.lav.macos-apps-mcp.plist"
cp "$REPO/packaging/Info.plist" "$APP/Contents/Info.plist"

# Smoke: env-free import through the bundled interpreter (getpath layout claim).
env -i "$APP/Contents/MacOS/macos-apps-mcp" -c "import macos_apps_mcp" \
  || { echo "BUNDLE SMOKE FAILED: getpath layout wrong"; exit 1; }

if [[ -n "$SIGN" ]]; then
  ENTS="$REPO/packaging/entitlements.plist"
  # inside-out: every nested Mach-O first, then the main binary, then the bundle
  find "$APP/Contents/lib" \( -name '*.so' -o -name '*.dylib' \) -print0 |
    while IFS= read -r -d '' f; do
      codesign --force --timestamp --options runtime -s "$SIGN" "$f"
    done
  codesign --force --timestamp --options runtime --entitlements "$ENTS" \
    -s "$SIGN" "$APP/Contents/MacOS/macos-apps-mcp"
  codesign --force --timestamp --options runtime --entitlements "$ENTS" \
    -s "$SIGN" "$APP"
  codesign --verify --strict --verbose=2 "$APP"
fi

if [[ -n "$NOTARIZE" ]]; then
  ditto -c -k --keepParent "$APP" "$OUT/macos-apps-mcp.zip"
  xcrun notarytool submit "$OUT/macos-apps-mcp.zip" \
    --keychain-profile "$NOTARIZE" --wait
  xcrun stapler staple "$APP"
fi
echo "built: $APP"
