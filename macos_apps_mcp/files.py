"""Where mail stops being mail and becomes a file on disk (#81 save, #85 export).

Every other mail module treats a message as data to cite. These two features write it
out, and that changes the threat model completely: **an attachment's NAME is
attacker-controlled** — it arrives in inbound mail from anyone — and this is the first
place in the repo that turns untrusted mail into a FILESYSTEM PATH.

So the rules live here, once, and both features route through them:

* The basename is **DERIVED**, never concatenated. The last component under every
  separator convention macOS has ever used (POSIX ``/``, Windows ``\\``, HFS ``:``),
  with C0/C1 controls, NULs and Unicode format characters removed — U+202E
  RIGHT-TO-LEFT OVERRIDE makes the real name ``invoice‮gpj.exe`` *display* as
  ``invoiceexe.jpg`` and is not a path character, so no amount of path checking
  catches it. A leading dot is
  prefixed away (an attachment must not become a dotfile) and a name that reduces to
  nothing, ``.`` or ``..`` falls back to a fixed literal.
* The destination is inside an **allowlisted root**, and containment is checked AFTER
  ``resolve()`` — a symlink inside the root that points at ``/`` passes an un-resolved
  check. The root is ``~/Downloads`` (where a user already expects a downloaded
  attachment, and never a code or config location); ``MACOS_APPS_FILE_ROOT`` moves it.
  The model picks a path INSIDE it — the tools ask for a ``dest_dir`` rather than
  defaulting to somewhere and hoping.
* An existing file is **never silently overwritten**. Mail's own ``save`` verb does
  overwrite silently — device-verified 2026-08-05, a 0-byte placeholder came back with
  192 KB in it — so the refusal has to happen in Python, before the Apple Event.
* Writes are **size-capped**, and a file that lands empty is removed and reported as a
  failure rather than left looking like a successful save.

``target_path`` checks existence and then hands back a path someone else writes to, so
there is a TOCTOU window between the check and Mail's ``save``. That is accepted: the
window is milliseconds, the root is the user's own Downloads directory, and closing it
properly (O_EXCL) is not available through an Apple Event that opens the file itself.
"""

from __future__ import annotations

import os
import unicodedata
from pathlib import Path

_FALLBACK = "attachment"

# 25 MiB — above every mainstream provider's own attachment ceiling, so a refusal here
# means something genuinely unusual rather than a normal mail this tool cannot handle.
MAX_BYTES = 25 * 1024 * 1024

# Enough for any real filename; short enough to survive a further path prefix on any
# filesystem (APFS caps a component at 255 BYTES, not characters).
_MAX_NAME_BYTES = 200

_DEFAULT_ROOT = "~/Downloads"

# Unicode general categories that must never reach a filename: control (Cc), format
# (Cf — the bidi overrides), surrogate (Cs), private-use (Co) and unassigned (Cn).
_FORBIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})


def root() -> Path:
    """The one directory anything here may write into. Read per call, not cached: the
    env var is how an operator moves it, and a cached value would need a restart."""
    return Path(os.environ.get("MACOS_APPS_FILE_ROOT") or _DEFAULT_ROOT).expanduser()


def safe_basename(name: str, fallback: str = _FALLBACK) -> str:
    """A hostile attachment name reduced to ONE filesystem-safe path component.

    Derived, never trusted: the input can be ``../../.ssh/authorized_keys``,
    ``/etc/passwd``, ``..\\..\\evil.dll``, ``HD:Users:me:.zshrc``, 4 KB of ``A``, a NUL
    in the middle, a bidi override, or empty.
    """
    n = unicodedata.normalize("NFC", name or "")
    n = "".join(c for c in n if unicodedata.category(c) not in _FORBIDDEN_CATEGORIES)
    # last component under every separator convention — POSIX, Windows, classic HFS
    for sep in ("/", "\\", ":"):
        n = n.rsplit(sep, 1)[-1]
    n = n.strip()
    if n in ("", ".", ".."):
        return fallback
    if n.startswith("."):
        # never let inbound mail create a dotfile
        n = "_" + n
    return _truncate(n)


def _truncate(name: str) -> str:
    """Bound the name to _MAX_NAME_BYTES, keeping the extension — the extension is what
    tells a human (and Finder) what the file is, so it is the last thing to lose."""
    if len(name.encode()) <= _MAX_NAME_BYTES:
        return name
    stem, dot, ext = name.rpartition(".")
    if not dot or len(ext.encode()) > 20:
        stem, ext = name, ""
        dot = ""
    budget = _MAX_NAME_BYTES - len((dot + ext).encode())
    out = stem.encode()[:budget].decode(errors="ignore")
    return out + dot + ext


def resolve_dest(dest_dir: str) -> Path:
    """The directory to write into: ``dest_dir`` under the allowlisted root, resolved,
    verified INSIDE the root, then created.

    ``dest_dir`` may be relative (joined onto the root) or absolute (it must then be the
    root or under it). Containment is checked after ``resolve()``, so a symlink pointing
    out of the root is refused rather than followed. Nothing is created until the path
    has passed — a refused destination must leave no trace.
    """
    base = root().expanduser().resolve()
    given = (dest_dir or "").strip()
    candidate = Path(given).expanduser() if given else base
    if not candidate.is_absolute():
        candidate = base / candidate
    resolved = candidate.resolve()
    if resolved != base and not resolved.is_relative_to(base):
        raise ValueError(
            f"{dest_dir!r} resolves outside the allowed root {base} — mail can only be "
            f"written under it. Pass a path inside {base}, or set MACOS_APPS_FILE_ROOT "
            "to move the root. Do not retry the same path."
        )
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def target_path(dest_dir: str, name: str, fallback: str = _FALLBACK) -> Path:
    """The full path to write ``name`` to — sanitized, contained, and PROVEN not to
    exist yet. Raises ``FileExistsError`` rather than overwriting."""
    directory = resolve_dest(dest_dir)
    path = (directory / safe_basename(name, fallback)).resolve()
    # belt and braces: safe_basename cannot emit a separator, so this cannot fail —
    # which is exactly why it is cheap to assert rather than to reason about.
    if not path.is_relative_to(directory):
        raise ValueError(f"refusing to write outside {directory}")
    if path.exists():
        raise FileExistsError(
            f"{path} already exists — this never overwrites. Choose another dest_dir, "
            "or move the existing file out of the way first."
        )
    return path


def check_size(size: int | None, name: str) -> None:
    """Refuse an oversized write BEFORE anything is fetched or created. ``None`` (Mail
    could not report a size) passes — ``confirm_written`` is the backstop."""
    if size is not None and size > MAX_BYTES:
        raise ValueError(
            f"{name!r} is {size} bytes, larger than the {MAX_BYTES}-byte cap. Save it "
            "from Mail directly. Do not retry."
        )


def confirm_written(path: Path) -> int:
    """Byte count of what actually landed. A 0-byte file is deleted and reported as a
    failure: Mail fetches an undownloaded attachment on demand (device-verified), but
    an offline account cannot, and an empty file that looks like a successful save is
    the reassuring-direction lie this repo keeps refusing."""
    size = path.stat().st_size
    if size == 0:
        path.unlink(missing_ok=True)
        raise ValueError(
            f"{path.name} was written as 0 bytes and has been removed — the attachment "
            "is not available locally (the account may be offline, or the message not "
            "downloaded). Open the message in Mail once, then retry."
        )
    return size
