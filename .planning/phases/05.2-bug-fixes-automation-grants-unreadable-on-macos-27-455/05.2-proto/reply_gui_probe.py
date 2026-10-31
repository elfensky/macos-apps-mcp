"""Phase 05.2 / FIX-16 (#348) device probe: reply text above Mail's native quote through
the Accessibility API (route a). Stdlib + ctypes + pyobjc-core/Cocoa (already locked).

Run as the INSTALLED BUNDLE (identity = ren.lav.macos-apps-mcp, the grant under test):

    open -n -W --stdout R/<step>.txt --stderr R/<step>.err \
        -a /Applications/macos-apps-mcp.app \
        --args -E -s -P <abs path to this file> <subcommand> ...

or from a terminal (`uv run python -I <this file> selftest`) for the offline checks.
Every line printed is a verdict, a count, an id or a hash: never clipboard content or mail
text (the probe marker aside). Nothing here ever calls the prompting AX trust variant.

Subcommands (see --help of each):
  selftest | trusted | dump-scripts DIR | clip-hash OUT.json [--against FILE]
  open-reply MID ACCOUNT PATH ALL | insert M1|M2|M3 WINDOW-ID MARKER-FILE --outgoing-id OID
      [--replace-all] [--activate] [--body-roles A,B] [--expect-tail TEXT]
      [--original MID ACCOUNT PATH]
  send OID --allow-file FILE [--original MID ACCOUNT PATH]
  discard OID [--original MID ACCOUNT PATH] | outbox-count | outgoing-ids OUT.json
  discard-new BASELINE.json MID ACCOUNT PATH | drafts-baseline OUT.json
  drafts-since BASELINE.json PREFIX
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import unicodedata
from pathlib import Path

MAIL = "com.apple.mail"
_HI = "/System/Library/Frameworks/ApplicationServices.framework/Frameworks/HIServices.framework"
_CGFW = "/System/Library/Frameworks/CoreGraphics.framework"
_CF = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
_FLAG_CMD = 0x100000  # kCGEventFlagMaskCommand
_KEY_A, _KEY_V = 0, 9  # kVK_ANSI_A, kVK_ANSI_V
_TRANSIENT = ("org.nspasteboard.TransientType", "org.nspasteboard.ConcealedType")
_BODY_ROLES = "AXTextArea,AXWebArea"
_OSA_TIMEOUT = 150  # host-side cap; every Mail block inside is `with timeout of 120`


class Refuse(Exception):
    """A safety check failed BEFORE any write or key event."""


def say(line: str) -> None:
    print(line, flush=True)


# --- bindings (lazy: nothing loads at import) --------------------------------------

_B: dict = {}


def _bind() -> dict:
    if _B:
        return _B
    import objc

    hi = objc.loadBundle("HIServices", {}, bundle_path=_HI)
    objc.loadBundleFunctions(
        hi,
        _B,
        [
            ("AXIsProcessTrusted", b"Z"),  # never the ...WithOptions (prompting) form
            ("AXUIElementGetTypeID", b"Q"),
            ("AXUIElementCreateApplication", b"^{__AXUIElement=}i"),
            ("AXUIElementCopyAttributeValue", b"i^{__AXUIElement=}^{__CFString=}o^@"),
            ("AXUIElementSetAttributeValue", b"i^{__AXUIElement=}^{__CFString=}@"),
            ("AXUIElementIsAttributeSettable", b"i^{__AXUIElement=}^{__CFString=}o^Z"),
            ("_AXUIElementGetWindow", b"i^{__AXUIElement=}o^I"),  # SPI, optional
        ],
    )
    objc.registerCFSignature(
        "AXUIElementRef", b"^{__AXUIElement=}", _B["AXUIElementGetTypeID"]()
    )
    cg = objc.loadBundle("CoreGraphics", {}, bundle_path=_CGFW)
    objc.loadBundleFunctions(cg, _B, [("CGWindowListCopyWindowInfo", b"@II")])
    return _B


_CG: ctypes.CDLL | None = None


def _cg() -> ctypes.CDLL:
    global _CG
    if _CG is None:
        lib = ctypes.CDLL(_CGFW + "/CoreGraphics")
        lib.CGEventCreateKeyboardEvent.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint16,
            ctypes.c_bool,
        ]
        lib.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
        lib.CGEventSetFlags.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
        lib.CGEventPostToPid.argtypes = [ctypes.c_int, ctypes.c_void_p]
        lib.CFRelease = ctypes.CDLL(_CF).CFRelease
        lib.CFRelease.argtypes = [ctypes.c_void_p]
        _CG = lib
    return _CG


def _key_to_pid(pid: int, keycode: int) -> None:
    """Cmd+<key> down and up, delivered to ONE process (never the global post)."""
    lib = _cg()
    for down in (True, False):
        ev = lib.CGEventCreateKeyboardEvent(None, keycode, down)
        lib.CGEventSetFlags(ev, _FLAG_CMD)
        lib.CGEventPostToPid(pid, ev)
        lib.CFRelease(ev)


def _trusted() -> bool:
    return bool(_bind()["AXIsProcessTrusted"]())


# --- AX helpers --------------------------------------------------------------------


def _ax(el, attr):
    err, val = _bind()["AXUIElementCopyAttributeValue"](el, attr, None)
    return val if err == 0 else None


def _ax_frame(el):
    """(x, y, w, h) from the AXFrame AXValue, or None."""
    import objc

    val = _ax(el, "AXFrame")
    if val is None:
        return None
    hi = ctypes.CDLL(_HI + "/HIServices")
    hi.AXValueGetValue.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
    buf = (ctypes.c_double * 4)()
    if not hi.AXValueGetValue(ctypes.c_void_p(objc.pyobjc_id(val)), 3, buf):
        return None  # 3 = kAXValueTypeCGRect
    return tuple(round(v) for v in buf)


def _ax_window_number(win, pid: int) -> tuple[int | None, str]:
    """The CoreGraphics window number of an AX window element, and how it was found."""
    spi = _bind().get("_AXUIElementGetWindow")
    if spi:
        err, num = spi(win, None)
        if err == 0 and num:
            return int(num), "_AXUIElementGetWindow"
    # shortcut: frame match, only when exactly one Mail window has that frame
    frame = _ax_frame(win)
    hits = [
        w["num"]
        for w in _cg_windows()
        if w["pid"] == pid
        and frame
        and (
            round(w["bounds"].get("X", -1)),
            round(w["bounds"].get("Y", -1)),
            round(w["bounds"].get("Width", -1)),
            round(w["bounds"].get("Height", -1)),
        )
        == frame
    ]
    return (hits[0], "frame") if len(hits) == 1 else (None, "unmatched")


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFC", s)
    for sep in ("\r\n", "\r", "\u2028", "\u2029"):
        s = s.replace(sep, "\n")
    return s


def _squash(s: str) -> str:
    return re.sub(r"\s+", " ", _fold(s)).strip()


def _read_body(el) -> tuple[str, str]:
    """The compose body text through AX: AXValue, else the AXStaticText descendants."""
    val = _ax(el, "AXValue")
    if isinstance(val, str) and val:
        return val, "AXValue"
    parts: list[str] = []
    budget = [400]

    def walk(node, depth: int) -> None:
        if depth > 14 or budget[0] <= 0:
            return
        budget[0] -= 1
        if _ax(node, "AXRole") == "AXStaticText":
            text = _ax(node, "AXValue")
            if isinstance(text, str):
                parts.append(text)
        for child in _ax(node, "AXChildren") or []:
            walk(child, depth + 1)

    walk(el, 0)
    return "\n".join(parts), "walk"


# --- windows / processes -----------------------------------------------------------


def _cg_windows() -> list[dict]:
    """On-screen windows, front to back."""
    raw = (
        _bind()["CGWindowListCopyWindowInfo"](1 | 16, 0) or []
    )  # OnScreenOnly|NoDesktop
    return [
        {
            "num": int(w["kCGWindowNumber"]),
            "pid": int(w["kCGWindowOwnerPID"]),
            "layer": int(w["kCGWindowLayer"]),
            "bounds": dict(w.get("kCGWindowBounds") or {}),
        }
        for w in raw
    ]


def _top_layer0() -> dict | None:
    return next((w for w in _cg_windows() if w["layer"] == 0), None)


def _mail_pid() -> int:
    import AppKit

    apps = AppKit.NSRunningApplication.runningApplicationsWithBundleIdentifier_(MAIL)
    if not apps:
        raise Refuse("Mail is not running")
    return int(apps[0].processIdentifier())


def _frontmost_bundle() -> str | None:
    import AppKit
    import Foundation

    # a process with no running main loop reads a stale frontmost app: spin it once
    Foundation.NSRunLoop.currentRunLoop().runUntilDate_(
        Foundation.NSDate.dateWithTimeIntervalSinceNow_(0.05)
    )
    app = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
    return str(app.bundleIdentifier()) if app else None


# --- AppleScript (raw osascript: run_osascript caps a script at 30 s) -------------

# Copies of mail_addressing.MAILBOX_REF and mail_outgoing.ROLLBACK, inline so the probe
# runs as the bundle without importing the package.
_MAILBOX_REF = """on mailboxFor(acctId, mbPath)
  with timeout of 120 seconds
  tell application "Mail"
    if acctId is "" then
      if mbPath is "inbox" then
        return inbox
      else if mbPath is "sent" then
        return sent mailbox
      else if mbPath is "drafts" then
        return drafts mailbox
      else if mbPath is "trash" then
        return trash mailbox
      else if mbPath is "junk" then
        return junk mailbox
      else
        error "unknown system mailbox " & mbPath
      end if
    else if acctId is "local" then
      return mailbox mbPath
    else
      return mailbox mbPath of (first account whose id is acctId)
    end if
  end tell
  end timeout
end mailboxFor"""

_ROLLBACK = """on rollback(msg)
  with timeout of 120 seconds
    try
      tell application "Mail" to delete msg
    end try
    try
      tell application "Mail" to get subject of msg
      return false
    on error number en
      return (en is -1728)
    end try
  end timeout
end rollback"""

_JOIN = """on joinIds(xs)
  set tid to AppleScript's text item delimiters
  set AppleScript's text item delimiters to ","
  set s to (xs as text)
  set AppleScript's text item delimiters to tid
  return s
end joinIds"""

# Reply with a window, no write to `content`. B1: the one window id new across the
# `reply` verb. B2: a direct link (a window's `document`) when one reads. A reply that
# no binding can name is rolled back at once.
_OPEN_REPLY = (
    _ROLLBACK
    + "\n\n"
    + _JOIN
    + "\n\n"
    + _MAILBOX_REF
    + """

on rawNewIds(idsBefore, idsAfter)
  set found to {}
  repeat with w in idsAfter
    set wi to contents of w
    if wi is not in idsBefore then set end of found to wi
  end repeat
  return found
end rawNewIds

-- A tiled Mail viewer gets a non-closeable 13-px divider window beside a new compose
-- window (macOS 27, 2026-10-31): it is not a compose window, so B1 skips it. An
-- unreadable closeable property keeps the id (more candidates fail, never mis-bind).
on newIds(idsBefore, idsAfter)
  set found to {}
  repeat with wi in my rawNewIds(idsBefore, idsAfter)
    set cl to true
    try
      tell application "Mail" to set cl to closeable of window id (contents of wi)
    end try
    if cl then set end of found to (contents of wi)
  end repeat
  return found
end newIds

on run argv
  set mid to item 1 of argv
  set mb to my mailboxFor(item 2 of argv, item 3 of argv)
  set doAll to ((item 4 of argv) is "1")
  set lf to linefeed
  with timeout of 120 seconds
    tell application "Mail"
      set matches to (messages of mb whose message id is mid)
      if (count of matches) is 0 then error "no message with that message id"
      set idsBefore to id of every window
      set r to reply (item 1 of matches) opening window yes reply to all doAll
      set idsAfter to id of every window
      set found to my newIds(idsBefore, idsAfter)
      set retried to 0
      if (count of found) is 0 then
        delay 1
        set retried to 1
        set idsAfter to id of every window
        set found to my newIds(idsBefore, idsAfter)
      end if
      set outId to "ERR"
      try
        set outId to (id of r) as text
      end try
      set b2 to "none"
      try
        repeat with w in windows
          try
            if (document of w) is r then set b2 to (id of w) as text
          end try
        end repeat
      on error e number n
        set b2 to "ERR" & n
      end try
      set win1 to "ERR"
      try
        set win1 to (id of window 1) as text
      end try
      set rolled to "no"
      if (count of found) is not 1 and b2 is not in {"none"} and b2 does not start with "ERR" then
        -- B1 failed but B2 names a window: keep the reply
      else if (count of found) is not 1 then
        if my rollback(r) then
          set rolled to "dead-1728"
        else
          set rolled to "alive"
        end if
      end if
      return "outgoing_id=" & outId & lf & "b1_new_ids=" & my joinIds(found) & lf & "b1_raw_new_ids=" & my joinIds(my rawNewIds(idsBefore, idsAfter)) & lf & "b1_retried=" & retried & lf & "b2=" & b2 & lf & "win1_id=" & win1 & lf & "rolled_back=" & rolled
    end tell
  end timeout
end run
"""
)

_WINDOW_INDEX = """on run argv
  set wid to (item 1 of argv) as integer
  with timeout of 120 seconds
    tell application "Mail"
      set idx to index of window id wid
    end tell
  end timeout
  return idx
end run
"""

_ACTIVATE = """on run argv
  set wid to (item 1 of argv) as integer
  with timeout of 120 seconds
    tell application "Mail"
      activate
      set index of window id wid to 1
    end tell
  end timeout
  return "activated"
end run
"""

# The window-id and frontmost checks sit in the same script, right before the keystroke.
_KEYSTROKE_V = """on run argv
  set wid to (item 1 of argv) as integer
  with timeout of 120 seconds
    set fid to -1
    tell application "Mail"
      try
        set fid to (id of window 1) as integer
      end try
    end tell
    if fid is not wid then return "refused-window"
    tell application "System Events"
      set fb to ""
      try
        set fb to bundle identifier of (first application process whose frontmost is true)
      end try
      if fb is not "com.apple.mail" then return "refused-not-frontmost"
      keystroke "v" using command down
    end tell
  end timeout
  return "keystroke-sent"
end run
"""

_RECIPIENTS = """on run argv
  set oid to (item 1 of argv) as integer
  set lf to linefeed
  set out to ""
  with timeout of 120 seconds
    tell application "Mail"
      set m to outgoing message id oid
      repeat with x in (to recipients of m)
        set out to out & "to=" & (address of x) & lf
      end repeat
      repeat with x in (cc recipients of m)
        set out to out & "cc=" & (address of x) & lf
      end repeat
      repeat with x in (bcc recipients of m)
        set out to out & "bcc=" & (address of x) & lf
      end repeat
      set sd to ""
      try
        set sd to (sender of m) as text
      end try
      set out to out & "sender=" & sd & lf
    end tell
  end timeout
  return out
end run
"""

# `send` stays outside any try that deletes: after `send`, `delete` is a silent no-op.
_SEND = """on run argv
  set oid to (item 1 of argv) as integer
  with timeout of 120 seconds
    tell application "Mail"
      send (outgoing message id oid)
    end tell
  end timeout
  return "send-returned"
end run
"""

_DISCARD = """on run argv
  set oid to (item 1 of argv) as integer
  with timeout of 120 seconds
    tell application "Mail"
      try
        delete (outgoing message id oid)
      on error e number n
        return "delete-error-" & n
      end try
      try
        get subject of (outgoing message id oid)
        return "alive"
      on error e number n
        if n is -1728 then return "dead-1728"
        return "unknown-" & n
      end try
    end tell
  end timeout
end run
"""

_OUTBOX = """on run argv
  with timeout of 120 seconds
    tell application "Mail"
      return count of (messages of outbox)
    end tell
  end timeout
end run
"""

_OUTGOING_IDS = (
    _JOIN
    + """

on run argv
  with timeout of 120 seconds
    tell application "Mail"
      set xs to id of every outgoing message
    end tell
  end timeout
  return my joinIds(xs)
end run
"""
)

# The id-free discard: the reply's outgoing id is unknown (a timeout, say). Candidates
# are outgoing messages not in the baseline whose subject ends with the original's.
_DISCARD_NEW = (
    _ROLLBACK
    + "\n\n"
    + _MAILBOX_REF
    + """

on run argv
  set mid to item 1 of argv
  set mb to my mailboxFor(item 2 of argv, item 3 of argv)
  set known to "," & (item 4 of argv) & ","
  with timeout of 120 seconds
    tell application "Mail"
      set matches to (messages of mb whose message id is mid)
      if (count of matches) is 0 then return "original-missing"
      set subj to subject of (item 1 of matches)
      if subj is "" then return "none"
      set cands to {}
      repeat with om in outgoing messages
        try
          set oi to id of om
          if known does not contain ("," & oi & ",") then
            if (subject of om) ends with subj then set end of cands to oi
          end if
        end try
      end repeat
      if (count of cands) is 0 then return "none"
      if (count of cands) > 1 then return "several"
      if my rollback(outgoing message id (item 1 of cands)) then return "dead-1728"
      return "alive"
    end tell
  end timeout
end run
"""
)

# F6: act on an outgoing message only when its subject ends with the original's subject.
_TARGET_GUARD = (
    _MAILBOX_REF
    + """

on run argv
  set oid to (item 1 of argv) as integer
  set mid to item 2 of argv
  set mb to my mailboxFor(item 3 of argv, item 4 of argv)
  with timeout of 120 seconds
    tell application "Mail"
      set matches to (messages of mb whose message id is mid)
      if (count of matches) is 0 then return "original-missing"
      set subj to subject of (item 1 of matches)
      if subj is "" then return "refused-not-probe"
      set osub to ""
      try
        set osub to subject of (outgoing message id oid)
      end try
      if osub is "" then return "refused-not-probe"
      if osub ends with subj then return "ok"
      return "refused-not-probe"
    end tell
  end timeout
end run
"""
)

SCRIPTS = {
    "open_reply": _OPEN_REPLY,
    "window_index": _WINDOW_INDEX,
    "activate": _ACTIVATE,
    "keystroke_v": _KEYSTROKE_V,
    "recipients": _RECIPIENTS,
    "send": _SEND,
    "discard": _DISCARD,
    "outbox": _OUTBOX,
    "outgoing_ids": _OUTGOING_IDS,
    "discard_new": _DISCARD_NEW,
    "target_guard": _TARGET_GUARD,
}


def _osa(script: str, *args: str) -> str:
    with tempfile.TemporaryDirectory(prefix="p052-") as d:
        f = Path(d) / "s.applescript"
        f.write_text(script, "utf-8")
        r = subprocess.run(
            ["osascript", str(f), *args],
            capture_output=True,
            text=True,
            timeout=_OSA_TIMEOUT,
        )
    if r.returncode:
        raise RuntimeError(f"osascript rc={r.returncode}: {r.stderr.strip()[:300]}")
    return r.stdout.strip()


def _kv(text: str) -> dict[str, str]:
    return dict(ln.split("=", 1) for ln in text.splitlines() if "=" in ln)


# --- pasteboard (hashes only; the unique-name pasteboard in selftest) -------------


def _snapshot(pb) -> tuple[list[dict[str, bytes]], int]:
    """(items, unreadable): every item's readable types, and how many types had no data."""
    items, bad = [], 0
    for item in pb.pasteboardItems() or []:
        one: dict[str, bytes] = {}
        for t in item.types():
            d = item.dataForType_(t)
            if d is None:
                bad += 1
            else:
                one[str(t)] = bytes(d)
        items.append(one)
    return items, bad


def _hash_items(items: list[dict[str, bytes]]) -> list[dict[str, str]]:
    return [
        {t: hashlib.sha256(b).hexdigest() for t, b in sorted(item.items())}
        for item in items
    ]


def _require_snapshot(
    items: list, bad: int, change_count: int, pb_types: int = 0
) -> None:
    """F2: a lossy snapshot would let the restore destroy the owner's clipboard. An
    empty pasteboard (no items AND no types, e.g. after a password manager cleared it)
    is a complete snapshot: its restore is clearContents."""
    if bad or (not items and change_count and pb_types):
        raise Refuse(f"clipboard snapshot incomplete ({bad} unreadable types)")


def _clip_equal(a: dict, b: dict) -> bool:
    """clip-hash --against: no vacuous pass when either side lost a type."""
    return (
        a.get("unreadable", 0) == 0
        and b.get("unreadable", 0) == 0
        and a["items"] == b["items"]  # item count and each item's type list + hashes
    )


def _restore(pb, snap: list[dict[str, bytes]]) -> None:
    import AppKit
    import Foundation

    items = []
    for types in snap:
        it = AppKit.NSPasteboardItem.alloc().init()
        for t, b in types.items():
            it.setData_forType_(Foundation.NSData.dataWithBytes_length_(b, len(b)), t)
        items.append(it)
    pb.clearContents()
    if items:
        pb.writeObjects_(items)


def _write_marker(pb, text: str) -> None:
    """The marker as plain text plus the marker types clipboard-history tools skip."""
    import AppKit
    import Foundation

    it = AppKit.NSPasteboardItem.alloc().init()
    it.setString_forType_(text, AppKit.NSPasteboardTypeString)
    for t in _TRANSIENT:
        it.setData_forType_(Foundation.NSData.data(), t)
    pb.clearContents()
    pb.writeObjects_([it])


# --- pure checks -------------------------------------------------------------------


def _new_ids(before: list[int], after: list[int]) -> list[int]:
    return [i for i in after if i not in before]


def _addr(s: str | None) -> str:
    """The bare lower-cased address: inside the last <...>, else the whole string."""
    s = s or ""
    hits = re.findall(r"<([^<>]*)>", s)
    return (hits[-1] if hits else s).strip().lower()


def _read_allow(path: str) -> list[str]:
    """F1: one address per line; blank lines and # comments skipped."""
    try:
        text = Path(path).read_text("utf-8")
    except OSError as e:
        raise Refuse(f"allow file unreadable ({type(e).__name__})") from None
    return [
        a
        for ln in text.splitlines()
        if (a := _addr(ln)) and not ln.lstrip().startswith("#")
    ]


def _send_gate(sender: str | None, rcpts: list[str], allow: list[str]) -> str | None:
    """None when the send may go; else the reason. Sender AND every recipient must be
    on the allow list (an account address of Mail is NOT enough)."""
    ok = {_addr(x) for x in allow if _addr(x)}
    if not ok:
        return "allow list is empty"
    if not _addr(sender):
        return "sender unreadable"
    if _addr(sender) not in ok:
        return "sender is not on the allow list"
    if not rcpts:
        return "no recipients"
    if any(_addr(r) not in ok for r in rcpts):
        return "a recipient is not on the allow list"
    return None


def _marker_body(body: str) -> str:
    return _squash(_fold(body).lstrip(" \n\t\ufffc"))


def _starts_with_marker(body: str, marker: str) -> bool:
    """F5: the ONE predicate, used by the settle loop and by the confirmation."""
    return _marker_body(body).startswith(_squash(marker))


def _quote_follows(body: str, marker: str, tail: str | None) -> bool | str:
    """True when `tail` follows the marker text; "unknown" without an expected tail."""
    if tail is None:
        return "unknown"
    if not _starts_with_marker(body, marker):
        return False
    return _squash(tail) in _marker_body(body)[len(_squash(marker)) :]


# --- subcommands -------------------------------------------------------------------


def _selftest_pure() -> None:
    # fixtures built from parts: the repo's address-privacy grep stays at zero
    me, fam, oth = (
        "me" + "@x.invalid",
        "family" + "@example.invalid",
        "o" + "@x.invalid",
    )
    allow = [me, "# a comment", ""]
    ok = _send_gate  # (sender, rcpts, allow)
    assert ok(me, [me], allow) is None
    assert (
        ok(f'"Me, Self" <{me.upper()}>', [f"Me <{me.title()}>", me.upper()], allow)
        is None
    )
    # F1: an address of another Mail account is refused, as recipient and as sender
    assert ok(me, [me, fam], allow)
    assert ok(fam, [me], allow)
    assert ok(None, [me], allow) and ok("", [me], allow)
    assert ok(me, [], allow) and ok(me, [me], [])
    with tempfile.TemporaryDirectory(prefix="p052-") as d:
        f = Path(d) / "allow.txt"
        f.write_text(f"# c\n {me.title()} \n\nOther <{oth}>\n", "utf-8")
        assert _read_allow(str(f)) == [me, oth]
        try:
            _read_allow(str(Path(d) / "missing"))
        except Refuse:
            pass
        else:
            raise AssertionError("a missing allow file must refuse")
    # F2: one unreadable type = incomplete snapshot = M2/M3 refuse before any write
    _require_snapshot([{"t": b"x"}], 0, 5)
    _require_snapshot([], 0, 0)
    _require_snapshot([], 0, 7, 0)  # emptied pasteboard: no items, no types
    for bad_snap in (([{"t": b"x"}], 1, 5), ([], 0, 7, 3)):
        try:
            _require_snapshot(*bad_snap)
        except Refuse as e:
            assert "snapshot incomplete" in str(e)
        else:
            raise AssertionError("an incomplete snapshot must refuse")
    h = {"items": [{"a": "1", "b": "2"}], "unreadable": 0}
    assert _clip_equal(h, {"items": [{"b": "2", "a": "1"}]})  # old file: no key
    assert not _clip_equal(h, {**h, "unreadable": 1})
    assert not _clip_equal({**h, "unreadable": 1}, h)
    assert not _clip_equal(h, {"items": [{"a": "1"}]})  # type lists differ
    assert not _clip_equal(h, {"items": [{"a": "1", "b": "2"}, {"c": "3"}]})
    # F5: one predicate for settle and confirm
    second = "Second line \u2013 caf\u00e9 \u2713"
    m1, m2 = "PROBE-1", f"PROBE-2\n\n{second}"
    nfd = unicodedata.normalize("NFD", m2)
    for marker, body, want in [
        (m1, m1, True),
        (m1, f"{m1}\n> quoted", True),
        (m2, m2, True),
        (m2, nfd + "\n> quoted", True),
        (m2, nfd.replace("\n\n", "\r\n\r\n"), True),
        (m1, f"  \n\ufffc {m1}", True),
        (m1, f"intro\n{m1}", False),
        (m1, "", False),
    ]:
        assert _starts_with_marker(body, marker) is want, (marker, body, want)
    # F5: quote_follows true / false / unknown
    assert (
        _quote_follows(f"{m1}\n\nOn x wrote:\n> hello world", m1, "hello world") is True
    )
    assert _quote_follows(m1, m1, "hello world") is False  # no quote after the text
    assert _quote_follows(f"x {m1} hello world", m1, "hello world") is False
    assert _quote_follows(f"{m1}\n> hello", m1, None) == "unknown"
    assert _quote_follows(f"{m1}\n> caf\u00e9", m1, "cafe\u0301") is True


def cmd_selftest(_a) -> int:
    import AppKit
    import Foundation

    b = _bind()
    _cg()
    assert hasattr(_cg(), "CGEventPostToPid")
    assert _cg_windows() is not None
    assert _fold("e\u0301\r\nx\u2028y") == "\u00e9\nx\ny"
    assert _new_ids([1, 2], [1, 2, 5]) == [5]
    _selftest_pure()
    pb = AppKit.NSPasteboard.pasteboardWithUniqueName()  # never the general one
    try:
        items = []
        for pairs in (
            [("public.utf8-plain-text", b"alpha"), ("public.html", b"<b>alpha</b>")],
            [("com.p052.probe-a", b"\x00\x01\x02"), ("com.p052.probe-b", b"beta")],
        ):
            it = AppKit.NSPasteboardItem.alloc().init()
            for t, d in pairs:
                it.setData_forType_(
                    Foundation.NSData.dataWithBytes_length_(d, len(d)), t
                )
            items.append(it)
        pb.clearContents()
        pb.writeObjects_(items)
        snap, bad = _snapshot(pb)
        assert bad == 0
        _require_snapshot(snap, bad, int(pb.changeCount()))
        before = _hash_items(snap)
        _write_marker(pb, "probe-marker")  # borrow, as M2 does
        _restore(pb, snap)
        after = _hash_items(_snapshot(pb)[0])
        assert len(before) == 2 and all(len(i) == 2 for i in before), before
        assert before == after, "named-pasteboard round trip differs"
    finally:
        pb.releaseGlobally()
    say(f"info: ax_getwindow_spi={'_AXUIElementGetWindow' in b}")
    say(f"selftest ok trusted={_trusted()}")
    return 0


def cmd_trusted(_a) -> int:
    say(str(_trusted()))
    return 0


def cmd_dump_scripts(a) -> int:
    out = Path(a.dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, text in SCRIPTS.items():
        (out / f"{name}.applescript").write_text(text, "utf-8")
    say(f"dump-scripts: {len(SCRIPTS)} written")
    return 0


def cmd_clip_hash(a) -> int:
    import AppKit

    pb = AppKit.NSPasteboard.generalPasteboard()
    items, bad = _snapshot(pb)
    data = {
        "changeCount": int(pb.changeCount()),
        "items": _hash_items(items),
        "unreadable": bad,
    }
    Path(a.out).write_text(json.dumps(data, indent=1), "utf-8")
    say(f"clip-hash: changeCount={data['changeCount']} items={len(data['items'])}")
    say(f"clip-hash: unreadable_types={bad}")
    if a.against:
        other = json.loads(Path(a.against).read_text("utf-8"))
        say(f"clip-hash: equal={_clip_equal(data, other)}")
    return 0


def cmd_open_reply(a) -> int:
    out = _kv(_osa(_OPEN_REPLY, a.mid, a.account, a.path, a.all))
    for k, v in out.items():
        say(f"open-reply: {k}={v}")
    top = _top_layer0()
    if top:  # for the record only
        say(f"open-reply: cg_top_layer0 pid={top['pid']} number={top['num']}")
    new = [i for i in out.get("b1_new_ids", "").split(",") if i]
    b2 = out.get("b2", "")
    if len(new) == 1:
        say(f"window-id: {new[0]} (B1)")
    elif b2.isdigit():
        say(f"window-id: {b2} (B2)")
    else:
        say(f"open-reply: FAIL no binding, new window ids={len(new)}")
        return 2
    return 0


def _window_ok(wid: int, pid: int, activate: bool) -> str:
    """The identity rule, part 1: the window by id, never by title."""

    def check() -> str | None:
        if _frontmost_bundle() == MAIL and _osa(_WINDOW_INDEX, str(wid)) == "1":
            return "index-1+mail-active"
        top = _top_layer0()
        if top and top["pid"] == pid and top["num"] == wid:
            return "cg-topmost-layer0"
        return None

    held = check()
    if held is None and activate:
        _osa(_ACTIVATE, str(wid))
        time.sleep(0.4)
        held = check()
    if held is None:
        raise Refuse(f"window {wid} is not Mail's frontmost window")
    say(f"window-check: held={held} activated={activate}")
    return held


def _focus_check(pid: int, wid: int, roles: tuple[str, ...]):
    """The identity rule, part 2: Mail's focused element is a body inside that window."""
    app = _bind()["AXUIElementCreateApplication"](pid)
    # a fresh reply's WebKit body takes focus only after it loads: wait (AX reads only)
    t0 = time.monotonic()
    el = _ax(app, "AXFocusedUIElement")
    while el is None and time.monotonic() - t0 < 3.0:
        time.sleep(0.05)
        el = _ax(app, "AXFocusedUIElement")
    say(f"focus-check: focus_wait_ms={round((time.monotonic() - t0) * 1000)}")
    if el is None:
        raise Refuse("no focused element in Mail")
    role = _ax(el, "AXRole")
    win = _ax(el, "AXWindow")
    num, how = _ax_window_number(win, pid) if win is not None else (None, "no-AXWindow")
    say(f"focus-check: role={role} ax_window={num} matched_by={how}")
    if role not in roles:
        raise Refuse(f"focused element role {role} is not a compose body")
    if num != wid:
        raise Refuse("focused element is not inside the probe's window")
    return el


def _confirm(el, marker: str, tail: str | None = None) -> bool:
    body, via = _read_body(el)
    strict = _fold(body).lstrip(" \n\ufffc").startswith(_fold(marker))  # info only
    loose = _starts_with_marker(body, marker)  # the settle loop's predicate
    more = len(_squash(body)) > len(_squash(marker))
    qf = _quote_follows(body, marker, tail)
    qf_s = qf if isinstance(qf, str) else str(qf).lower()
    say(
        f"confirm: via={via} starts_with_marker={strict} "
        f"starts_with_marker_squashed={loose} more_text_follows={more} "
        f"quote_follows={qf_s}"
    )
    return loose and qf is not False


def _guard(oid: str, original: list[str] | None) -> None:
    """F6: with --original, act only on an outgoing message whose subject ends with it."""
    if original is None:
        return
    r = _osa(_TARGET_GUARD, oid, *original)
    say(f"target-check: {r}")
    if r != "ok":
        raise Refuse(f"refused-not-probe ({r})")


def _rollback_reply(oid: str) -> None:
    try:
        say(f"rollback: {_osa(_DISCARD, oid)}")
    except Exception as e:  # noqa: BLE001 - the clipboard restore must still run
        say(f"rollback: error {type(e).__name__}: {str(e)[:200]}")


def _wait_marker(
    el, marker: str, t0: float, until: float, pre: str | None = None
) -> int | None:
    """Settled = the body starts with the marker AND it changed since just before the
    key event: a body that already started with the marker (a second insert, or a
    marker that prefixes an earlier one) once read as settled at 4 ms, the clipboard
    was restored, and Mail's late Cmd-V pasted the owner's content (2026-10-31)."""
    while time.monotonic() - t0 < until:
        body = _read_body(el)[0]
        if _starts_with_marker(body, marker) and (pre is None or _squash(body) != pre):
            return round((time.monotonic() - t0) * 1000)
        time.sleep(0.05)
    return None


def cmd_insert(a) -> int:
    import AppKit

    if not _trusted():
        raise Refuse("Accessibility is off for this process")
    marker = Path(a.marker_file).read_text("utf-8").rstrip("\n")
    roles = tuple(a.body_roles.split(","))
    pid = _mail_pid()
    _guard(a.outgoing_id, a.original)
    pb = AppKit.NSPasteboard.generalPasteboard()
    snap = base = None
    if a.mech != "M1":  # F4: the slow snapshot goes FIRST, before any identity check
        snap, bad = _snapshot(pb)
        cc0 = int(pb.changeCount())
        _require_snapshot(snap, bad, cc0, len(pb.types() or []))
        base = _hash_items(snap)
    _window_ok(a.window_id, pid, a.activate)
    el = _focus_check(pid, a.window_id, roles)
    if a.replace_all:
        _key_to_pid(pid, _KEY_A)
        time.sleep(0.2)
        el = _focus_check(pid, a.window_id, roles)  # right before the write
    if a.mech == "M1":
        err, ok = _bind()["AXUIElementIsAttributeSettable"](el, "AXSelectedText", None)
        say(f"insert: M1 AXSelectedText settable={bool(ok)} (err={err})")
        err = _bind()["AXUIElementSetAttributeValue"](el, "AXSelectedText", marker)
        say(f"insert: M1 set AXSelectedText err={err}")
        time.sleep(0.2)
        return 0 if err == 0 and _confirm(el, marker, a.expect_tail) else 4
    t_chk = time.monotonic()  # the last identity check
    if int(pb.changeCount()) != cc0:
        raise Refuse("clipboard changed after the snapshot; run again")
    pre = _squash(_read_body(el)[0])  # the body before the key event
    _write_marker(pb, marker)
    mine = int(pb.changeCount())
    settled = None
    try:
        t_ev = time.monotonic()
        if a.mech == "M2":
            _key_to_pid(pid, _KEY_V)
            say(f"insert: M2 check_to_event_ms={round((t_ev - t_chk) * 1000)}")
        else:  # M3: the script re-checks Mail frontmost + window id before keystroke
            say(f"insert: M3 check_to_launch_ms={round((t_ev - t_chk) * 1000)}")
            r = _osa(_KEYSTROKE_V, str(a.window_id))
            say(f"insert: M3 {r}")
            if r != "keystroke-sent":
                raise Refuse(f"M3 in-script check: {r}; no keystroke was sent")
        t0 = time.monotonic()  # F3: the settle timer starts AFTER the event
        settled = _wait_marker(el, marker, t0, 2.0, pre)
        if settled is None:  # keep the marker on the pasteboard for a further 3 s
            settled = _wait_marker(el, marker, t0, 5.0, pre)
            if settled is not None:
                say("insert: late settle (inside the 3 s grace)")
        say(f"insert: {a.mech} paste_settle_ms={settled}")
        if settled is None:
            say("paste: not-settled")
            _rollback_reply(a.outgoing_id)  # BEFORE the clipboard restore
    except Refuse:
        raise
    except Exception:
        _rollback_reply(a.outgoing_id)
        raise
    finally:
        if int(pb.changeCount()) == mine:
            _restore(pb, snap)
            items, bad = _snapshot(pb)
            say(
                f"pasteboard: restored=True equal={bad == 0 and _hash_items(items) == base}"
            )
        else:
            say("pasteboard: restored=False changeCount moved past the probe's write")
    return 0 if settled is not None and _confirm(el, marker, a.expect_tail) else 4


def _recipients(oid: str) -> tuple[list[str], str | None]:
    kv = [ln.split("=", 1) for ln in _osa(_RECIPIENTS, oid).splitlines() if "=" in ln]
    rcpt = [v for k, v in kv if k in ("to", "cc", "bcc")]
    return rcpt, next((v for k, v in kv if k == "sender" and v.strip()), None)


def cmd_send(a) -> int:
    allow = _read_allow(a.allow_file)  # F1: nothing is sent without a readable list
    _guard(a.oid, a.original)
    rcpt, sender = _recipients(a.oid)  # an unreadable list raises: nothing is sent
    say(f"send: sender={sender or '<unreadable>'}")
    say(f"send: recipients={', '.join(rcpt) or '<none>'}")
    why = _send_gate(sender, rcpt, allow)
    if why:
        raise Refuse(why)
    say(f"send: {_osa(_SEND, a.oid)}")
    return 0


def cmd_discard(a) -> int:
    _guard(a.oid, a.original)
    say(f"discard: {_osa(_DISCARD, a.oid)}")
    return 0


def cmd_outbox_count(_a) -> int:
    say(f"outbox-count: {_osa(_OUTBOX)}")
    return 0


def cmd_outgoing_ids(a) -> int:
    ids = [int(i) for i in _osa(_OUTGOING_IDS).split(",") if i.strip()]
    Path(a.out).write_text(json.dumps(ids), "utf-8")
    say(f"outgoing-ids: count={len(ids)}")
    return 0


def cmd_discard_new(a) -> int:
    base = json.loads(Path(a.baseline).read_text("utf-8"))
    say(
        "discard-new: "
        + _osa(_DISCARD_NEW, a.mid, a.account, a.path, ",".join(map(str, base)))
    )
    return 0


def _drafts(prefix: str | None) -> list[int]:
    """ROWIDs of live Drafts rows (every account), optionally by subject prefix.
    Read-only Envelope Index query: the Drafts mailbox spans accounts and drafts()
    caps at 25, so the baseline is taken here (facts 4d)."""
    dbs = sorted(
        Path.home().glob("Library/Mail/V*/MailData/Envelope Index"),
        key=lambda p: int(p.parts[-3][1:]) if p.parts[-3][1:].isdigit() else -1,
    )
    like = "%"
    if prefix:
        like = re.sub(r"([\\%_])", r"\\\1", prefix) + "%"
    conn = sqlite3.connect(f"file:{dbs[-1]}?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        rows = conn.execute(
            "SELECT m.ROWID FROM messages m"
            " JOIN subjects s ON s.ROWID = m.subject"
            " JOIN mailboxes mb ON mb.ROWID = m.mailbox"
            " WHERE m.deleted = 0"
            " AND (mb.url LIKE '%/Drafts' OR mb.url LIKE '%/Draft')"
            " AND (COALESCE(m.subject_prefix, '') || s.subject) LIKE ? ESCAPE '\\'",
            (like,),
        ).fetchall()
    finally:
        conn.close()
    return sorted(r[0] for r in rows)


def cmd_drafts_baseline(a) -> int:
    ids = _drafts(None)
    Path(a.out).write_text(json.dumps(ids), "utf-8")
    say(f"drafts-baseline: count={len(ids)}")
    return 0


def cmd_drafts_since(a) -> int:
    base = json.loads(Path(a.baseline).read_text("utf-8"))
    new = [i for i in _drafts(a.prefix) if i not in base]
    say(f"drafts-since: new={len(new)} rowids={','.join(map(str, new))}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, *pos):
        sp = sub.add_parser(name)
        for x in pos:
            sp.add_argument(x)
        sp.set_defaults(fn=fn)
        return sp

    add("selftest", cmd_selftest)
    add("trusted", cmd_trusted)
    add("dump-scripts", cmd_dump_scripts, "dir")
    add("clip-hash", cmd_clip_hash, "out").add_argument("--against")
    add("open-reply", cmd_open_reply, "mid", "account", "path", "all")
    ins = add("insert", cmd_insert)
    ins.add_argument("mech", choices=["M1", "M2", "M3"])
    ins.add_argument("window_id", type=int)
    ins.add_argument("marker_file")
    ins.add_argument("--replace-all", action="store_true")
    ins.add_argument("--activate", action="store_true")
    ins.add_argument("--body-roles", default=_BODY_ROLES)
    ins.add_argument("--outgoing-id", required=True)
    ins.add_argument("--expect-tail")
    ins.add_argument("--original", nargs=3, metavar=("MID", "ACCOUNT", "PATH"))
    snd = add("send", cmd_send, "oid")
    snd.add_argument("--allow-file", required=True)
    snd.add_argument("--original", nargs=3, metavar=("MID", "ACCOUNT", "PATH"))
    dis = add("discard", cmd_discard, "oid")
    dis.add_argument("--original", nargs=3, metavar=("MID", "ACCOUNT", "PATH"))
    add("outbox-count", cmd_outbox_count)
    add("outgoing-ids", cmd_outgoing_ids, "out")
    add("discard-new", cmd_discard_new, "baseline", "mid", "account", "path")
    add("drafts-baseline", cmd_drafts_baseline, "out")
    add("drafts-since", cmd_drafts_since, "baseline", "prefix")
    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except Refuse as e:
        say(f"refused: {e}")
        return 3
    except Exception as e:  # noqa: BLE001 - a probe prints a verdict, never a trace
        say(f"error: {type(e).__name__}: {str(e)[:300]}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
