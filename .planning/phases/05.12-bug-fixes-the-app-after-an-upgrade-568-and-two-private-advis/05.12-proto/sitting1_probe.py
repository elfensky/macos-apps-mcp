"""Phase 05.12 device probe of the owner sittings (#585, #607, #609, #610, #611): the
measurements M1 to M9 of the research, and two helpers for sitting 2. Throwaway code.

It loads the Phase 05.2 probe (reply_gui_probe.py) by its path and reuses it: the
bindings, the Accessibility reads, the clipboard helpers, the scripts and `say`. The
Mail scripts of that probe are re-targeted in memory to `application id` (#585).

Run the offline checks as a plain process (standard library only):

    uv run --no-project python -I <this file> selftest | compile | verdicts RESULTS

Run a device subcommand as the INSTALLED BUNDLE (its grants are the ones under test):

    open -g -n -W --stdout R/<step>.txt --stderr R/<step>.err \
        -a /Applications/macos-apps-mcp.app --args -E -s -P <this file> <subcommand> ...

Every line goes through `say()`, which withholds a line with an at sign or a home
path. A line holds a verdict, a count, a time, a hash (12 hex of SHA-256) or the name
of a system bundle: never mail text, a subject, an address, clipboard content or
signature text. There is NO send command, and the send of the 05.2 probe is not
forwarded.

Key guard: every key event goes through `guarded_key`. It reads Mail's outgoing ids
first. An id outside the expected set prints `refused: another compose window`, and
no key is posted. Then the focus check runs again as the LAST check (the focused body
is inside the given window), before the clipboard write, the stop and the key.
A refusal or an error while a scratch reply may be open says `the scratch reply is
still open: discard it` (in the `refused:` line, else in a `note:` line). An `error:`
line holds only the exception type and an AppleScript error number.

A stop of Mail prints `mail_pid=<n>` first, lasts at most 10 s, and
the continue signal (SIGCONT) is sent in a `finally`, at exit, on SIGTERM/SIGINT and
by a detached `kill -CONT` backstop.

Subcommands and their output. `verdicts` reads ONLY the lines `<subcommand>: result
k=v ...` (one per run), `stored-diff: class n=<count> label=<text>` and `owner:
<key>=yes|no`, wherever they stand in the results file (a heading above them is not
needed; a leading list mark or back tick is ignored). Never write an `m<n>:` line
here: the orchestrator owns those.

  selftest                 -> `selftest ok forwarded=6 scripts=<n>`
  compile                  -> `compile: scripts=<n> failed=<n>` (osacompile only)
  verdicts RESULTS         -> nine lines `key: value` (607-cause, 607-poll-bound,
      609-signature-in-ax, 610-settle-bound, 610-drain-wait, 610-empty-paste,
      585-id-route, 585-other-apps, 611-real-mail)
  open-reply | discard | outgoing-ids | clip-hash | drafts-baseline | drafts-since
      forwarded to the 05.2 probe with its arguments and its output lines;
      `discard` is refused without `--original MID ACCOUNT PATH`
  app-path (M7, M8; can START an app) -> four lines
      `app-path: result app=mail|notes|messages|music running= ext_procs= by_name=
      running_mid= by_id= running_after=` (by_name, by_id: the last path part)
  id-read (M7; can START Mail) ->
      `id-read: result id_read=ok|err:<n> windows= ms= mail_running_before=
      mail_running_after=`
  hold-timeline WINDOW-ID [--after S] (M1, M2) ->
      `hold-timeline: at-trigger trigger_age_ms= front_bundle=`, then
      `hold-timeline: result trigger_age_ms= front_bundle= active_before=
      activate_ms= first_active_ms=<n>|never index_first_1_ms=<n>|never
      half=none|active|index|both samples= active_lost= index_reads= index_not_1=`
  paste-cycle MID ACCOUNT PATH [--after S] (M3; one whole cycle) ->
      the 05.2 `open-reply:` lines, `paste-cycle: at-trigger ...`, then
      `paste-cycle: result trigger_age_ms= front_bundle= mail_cpu= mail_uptime_s=
      mail_active= settle_ms=<n>|never|not-run samples= discard=ok|<word>
      window_left=yes|no restored=yes|no|not-written`
  empty-paste WINDOW-ID --outgoing-id N (M4) ->
      `empty-paste: result body_equal=yes|no|unreadable|not-run body_chars=
      hash_before= hash_after= restored=`
  stop-paste WINDOW-ID OUTGOING-ID --hand N --original MID ACCOUNT PATH (M5) ->
      `stop-paste: mail_pid=<n>` first, then `stop-paste: result mail_pid=
      stopped_ms= discard=ok|<word> discard_ms= key_seen_ms=<n>|none
      hand_changed=yes|no|unreadable late_ms=<n>|none window_left= restored=`.
      `discard_ms` and
      `key_seen_ms` count from the continue signal; `late_ms` is the time from the
      discard's answer to the first changed read of the hand window (0 when it
      changed before the answer).
  sig-ax WINDOW-ID OUTGOING-ID (M6) ->
      `sig-ax: result signature_read=yes|no in_ax_body=yes|no sig_chars=
      body_chars= via=`
  stored-diff --account ID [--budget S] (M9) ->
      `stored-diff: result files= parsed= html= differ= skipped_large= errors=
      mailboxes= partial=yes|no elapsed_s=`, then one
      `stored-diff: class n=<count> label=<input class>` for each class
  hand-hash -> `hand-hash: result found=<windows with P0512HAND> hash=<12 hex>|none
      outgoing_id=<n>|unknown outgoing_count=` (the id is known only while the hand
      window is the one outgoing message)
  stop-mail SECONDS [--wait S] (sitting 2) -> `stop-mail: mail_pid=<n>`, then
      `stop-mail: result mail_pid= window_seen=yes|no waited_ms= stopped_ms=`
"""

from __future__ import annotations

import argparse
import atexit
import contextlib
import ctypes
import hashlib
import importlib.util
import inspect
import io
import math
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
_P052 = (
    HERE.parents[1]
    / "05.2-bug-fixes-automation-grants-unreadable-on-macos-27-455"
    / "05.2-proto"
    / "reply_gui_probe.py"
)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


P = _load(_P052, "reply_gui_probe")  # standard library only at import

# #585: the 05.2 scripts name Mail; here every one of them addresses the bundle id.
_BY_NAME = 'tell application "Mail"'
_BY_ID = f'tell application id "{P.MAIL}"'
for _k, _v in list(vars(P).items()):
    if isinstance(_v, str) and _BY_NAME in _v:
        setattr(P, _k, _v.replace(_BY_NAME, _BY_ID))

MARKER_PASTE = "P0512PASTE"
MARKER_HAND = "P0512HAND"
FORWARDED = (
    "open-reply",
    "discard",
    "outgoing-ids",
    "clip-hash",
    "drafts-baseline",
    "drafts-since",
)
# Mirrors runtime.BUNDLE_IDS for the four apps of M7 and M8.
APPS = {
    "mail": ("Mail", "com.apple.mail"),
    "notes": ("Notes", "com.apple.Notes"),
    "messages": ("Messages", "com.apple.MobileSMS"),
    "music": ("Music", "com.apple.Music"),
}
HOLD_S = 5.0  # M1: the sampling window after the activation script
SETTLE_MAX_S = 30.0  # M3: the longest wait for the pasted text
STOP_S = 3.0  # M5: the length of the stop
STOP_MAX_S = 10.0  # no stop of Mail lasts longer
LARGE_BODY = 100_000  # M9: above this the old (quadratic) strip is skipped
_ROLES = tuple(P._BODY_ROLES.split(","))
_SOUND = "/System/Library/Sounds/Tink.aiff"

# --- output ------------------------------------------------------------------------

_LOG: list[str] = []
_PRINT = P.say
_HOME_MARKS = [m for m in (str(Path.home()), "/" + "Users" + "/") if len(m) > 1]


def _public(line: str) -> str:
    if line.startswith("error:"):
        # only the exception type and an AppleScript error number: never the
        # osascript text, a command line or an echoed argument
        kind = re.match(r"error:\s*([A-Za-z_][\w.]*)", line)
        num = re.search(r"\((-\d{1,6})\)", line)
        line = f"error: {kind[1] if kind else 'unknown'}"
        line += f" ({num[1]})" if num else ""
    if "@" in line or any(m in line for m in _HOME_MARKS):
        return "withheld: a line with private text was not printed"
    return line


def say(line: str) -> None:
    line = _public(str(line))
    _LOG.append(line)
    _PRINT(line)


P.say = say  # the forwarded subcommands print through the same guard


def _h(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _yn(flag) -> str:
    return "yes" if flag else "no"


def _ms(seconds: float) -> int:
    return round(seconds * 1000)


def _kv(res: dict) -> str:
    return " ".join(f"{k}={str(v).replace(' ', '_')}" for k, v in res.items())


# --- scripts (each block: its own timeout, Mail by bundle id) ----------------------

# app-path: the by-name read is the thing measured (#585), so it stays by name.
_PATH_BY_NAME = """on run argv
  with timeout of 120 seconds
    try
      return POSIX path of (path to application (item 1 of argv))
    on error e number n
      return "ERR" & n
    end try
  end timeout
end run
"""

_PATH_BY_ID = """on run argv
  with timeout of 120 seconds
    try
      return POSIX path of (path to application id (item 1 of argv))
    on error e number n
      return "ERR" & n
    end try
  end timeout
end run
"""

_ID_READ = """on run argv
  with timeout of 120 seconds
    try
      tell application id "com.apple.mail"
        set n to count of windows
      end tell
      return "ok" & n
    on error e number en
      return "ERR" & en
    end try
  end timeout
end run
"""

# One outgoing message's signature content, in the record form of the 05.2 _SIG_READ.
_SIG_OF = """on run argv
  set oid to (item 1 of argv) as integer
  set us to character id 31
  set rec to "missing"
  with timeout of 120 seconds
    tell application id "com.apple.mail"
      set sig to missing value
      try
        set sig to message signature of (outgoing message id oid)
      end try
      if sig is not missing value then
        set rec to "found" & us
        try
          set rec to rec & (content of sig)
        end try
      end if
    end tell
  end timeout
  return rec
end run
"""


def _scripts() -> dict[str, str]:
    """Every script that a subcommand of this probe can run (never the 05.2 send)."""
    return {
        "path_by_name": _PATH_BY_NAME,
        "path_by_id": _PATH_BY_ID,
        "id_read": _ID_READ,
        "sig_of": _SIG_OF,
        "open_reply": P._OPEN_REPLY,
        "discard": P._DISCARD,
        "outgoing_ids": P._OUTGOING_IDS,
        "target_guard": P._TARGET_GUARD,
        "window_index": P._WINDOW_INDEX,
        "activate": P._ACTIVATE,
    }


# Whether a scratch reply may be open now, and whether this run must discard it.
_SCRATCH = {"open": False, "owned": False}
_LEFT = "the scratch reply is still open: discard it"

# --- the key guard: the ONE door to a key event -------------------------------------


def _outgoing_ids() -> list[int]:
    return [int(i) for i in P._osa(P._OUTGOING_IDS).split(",") if i.strip()]


def guarded_key(
    expected, required, pid, before_post=None, *, focus, read_ids=None, post=None
):
    """Post Cmd-V to Mail only when its outgoing messages are the expected ones AND
    `focus()` then still passes. A hand-opened compose window may not be a scripting
    object, so the id read can be blind to it: the focus check is the LAST check, after
    the script round trip. `focus` raises a refusal or returns False to refuse.
    `before_post` (a clipboard write, a stop) runs after both checks, before the key."""
    ids = set((read_ids or _outgoing_ids)())
    if ids - set(expected):
        raise P.Refuse("another compose window")
    if not set(required) <= ids:
        raise P.Refuse("the scratch reply is not open")
    if focus() is False:
        raise P.Refuse("the focus check failed")
    if before_post:
        before_post()
    (post or P._key_to_pid)(pid, P._KEY_V)


# --- a bounded stop of Mail ---------------------------------------------------------

_STOPPED: set[int] = set()
_KILL = os.kill


def _continue_all(*_a) -> None:
    """SIGCONT to every pid this process stopped. Safe to call twice."""
    for pid in list(_STOPPED):
        with contextlib.suppress(OSError):
            _KILL(pid, signal.SIGCONT)
        _STOPPED.discard(pid)


def _on_signal(signum, _frame) -> None:
    _continue_all()  # SIGCONT before this process ends
    raise SystemExit(128 + signum)


def _arm() -> None:
    """A terminated run still runs each `finally` (clipboard restore, discard) and
    sends SIGCONT: the handler raises SystemExit, it does not exit hard."""
    atexit.register(_continue_all)  # SIGCONT at exit
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, _on_signal)


@contextlib.contextmanager
def mail_stopped(pid: int, arm: bool = True):
    """Mail is stopped inside the block. The continue signal goes out in the
    `finally`, at exit, on a signal, and from a detached backstop after 10 s (it
    covers a killed probe; a SIGCONT to a running Mail does nothing)."""
    if arm:
        _arm()
        subprocess.Popen(
            ["/bin/sh", "-c", f"sleep {int(STOP_MAX_S)}; kill -CONT {int(pid)}"],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    _STOPPED.add(pid)
    try:
        try:
            _KILL(pid, signal.SIGSTOP)
        except PermissionError:
            raise P.Refuse("the stop signal was not permitted") from None
        yield
    finally:
        _continue_all()


def _sleep_until(end: float) -> None:
    while (rest := end - time.monotonic()) > 0:
        time.sleep(min(rest, 0.05))


# --- pure helpers ---------------------------------------------------------------------


def summarize(active: list, index: list) -> dict:
    """M1: `active` = (ms, AXFrontmost) samples, `index` = (ms, window index) reads."""
    first = next((t for t, on in active if on), None)
    lost = first is not None and any(not on for t, on in active if t > first)
    one = next((t for t, i in index if i == 1), None)
    since = first if first is not None else 0
    not_1 = sum(1 for t, i in index if t >= since and i != 1)
    halves = {
        (True, True): "none",
        (False, True): "active",
        (True, False): "index",
        (False, False): "both",
    }
    return {
        "first_active_ms": "never" if first is None else first,
        "index_first_1_ms": "never" if one is None else one,
        "half": halves[(first is not None, bool(index) and not_1 == 0)],
        "samples": len(active),
        "active_lost": _yn(lost),
        "index_reads": len(index),
        "index_not_1": not_1,
    }


def _proc_counts(comm_lines: list[str], bundle: str) -> tuple[bool, int]:
    """(the app runs, processes from inside its bundle that are not the app)."""
    main = bundle + "/Contents/MacOS/"
    inside = [ln for ln in comm_lines if ln.startswith(bundle + "/")]
    return any(ln.startswith(main) for ln in inside), sum(
        1 for ln in inside if not ln.startswith(main)
    )


def _etime_s(etime: str) -> int | None:
    """ps etime `[[dd-]hh:]mm:ss` in seconds."""
    m = re.fullmatch(r"(?:(?:(\d+)-)?(\d+):)?(\d+):(\d+)", etime.strip())
    if not m:
        return None
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return ((d * 24 + h) * 60 + mi) * 60 + s


def _last_part(posix_path: str) -> str:
    return posix_path.strip().rstrip("/").rsplit("/", 1)[-1].replace(" ", "_") or "-"


# --- verdicts (pure; the rules of plan 05.12-01, Task 3) ------------------------------

_KEYS = (
    "607-cause",
    "607-poll-bound",
    "609-signature-in-ax",
    "610-settle-bound",
    "610-drain-wait",
    "610-empty-paste",
    "585-id-route",
    "585-other-apps",
    "611-real-mail",
)


def _records(text: str):
    recs: dict[str, list[dict[str, str]]] = {}
    owner: dict[str, str] = {}
    classes: list[tuple[int, str]] = []
    for raw in text.splitlines():
        line = raw.strip().lstrip("-*>` ").rstrip("` ")
        if m := re.match(r"([a-z-]+): result (.*)$", line):
            pairs = (p.split("=", 1) for p in m[2].split() if "=" in p)
            recs.setdefault(m[1], []).append(dict(pairs))
            if m[1] == "stored-diff":
                classes = []  # class lines belong to the result line above them
        elif m := re.match(r"owner: (\w+)=(yes|no)$", line):
            owner[m[1]] = m[2]
        elif m := re.match(r"stored-diff: class n=(\d+) label=(.*)$", line):
            classes.append((int(m[1]), m[2]))
    return recs, owner, classes


def _num(value) -> int | None:
    """A count or a time of a result line; None for anything else (never raises)."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def _nums(recs: list[dict], key: str) -> list[int]:
    return [n for r in recs if (n := _num(r.get(key))) is not None]


def _tenths(floor: int, largest_ms: int) -> int:
    """Twice the largest time, rounded up to 0.1 s, at least `floor` (in 0.1 s)."""
    return max(floor, -(-2 * largest_ms // 100))


def _group(run: dict) -> str:
    age = _num(run.get("trigger_age_ms"))
    if age is not None and age < 2000 and run.get("front_bundle") != P.MAIL:
        return "with"
    if age is not None and age >= 4000:
        return "without"
    return "neither"


def verdict_lines(text: str) -> list[str]:
    recs, owner, classes = _records(text)
    out: dict[str, str] = {}

    # M1, M2 (#607)
    runs = recs.get("hold-timeline", [])
    groups: dict[str, list[dict]] = {"with": [], "without": [], "neither": []}
    for run in runs:
        groups[_group(run)].append(run)
    usable = groups["with"] + groups["without"]
    if not usable:
        cause = "not measured"
    elif any(r.get("first_active_ms") == "never" for r in groups["with"]):
        cause = "declined activation"  # the plan: only a run WITH input
    elif any(r.get("half") == "index" for r in usable):
        cause = "index not held"
    elif max(_nums(usable, "first_active_ms"), default=0) > 400:
        cause = "late activation"
    else:
        cause = "not reproduced"
    ages = ",".join(r.get("trigger_age_ms", "?") for r in groups["neither"])
    halves = [r.get("half") for r in runs]
    out["607-cause"] = (
        f"{cause}; with input {len(_nums(groups['with'], 'first_active_ms'))} of "
        f"{len(groups['with'])} runs active inside 5 s; without input "
        f"{len(_nums(groups['without'], 'first_active_ms'))} of "
        f"{len(groups['without'])}; in neither group {len(groups['neither'])}"
        + (f" (trigger_age_ms {ages})" if ages else "")
        + f"; half false: active {halves.count('active')}, index "
        f"{halves.count('index')}, both {halves.count('both')}"
    )
    times = _nums(runs, "first_active_ms")
    if times:
        out["607-poll-bound"] = (
            f"{_tenths(20, max(times)) / 10:.1f} (largest {max(times)} ms to active "
            f"over {len(times)} runs that became active)"
        )
    else:
        out["607-poll-bound"] = "2.0 (not measured; the default of D6)"

    # M6 (#609)
    sig = (recs.get("sig-ax") or [{}])[-1]
    ok = sig.get("signature_read") == "yes" and sig.get("in_ax_body") in ("yes", "no")
    out["609-signature-in-ax"] = sig["in_ax_body"] if ok else "not available"

    # M3 (#610)
    pastes = recs.get("paste-cycle", [])
    settled = _nums(pastes, "settle_ms")
    never = sum(1 for r in pastes if r.get("settle_ms") == "never")
    settle = _tenths(10, max(settled)) if settled else 10
    if settled:
        out["610-settle-bound"] = (
            f"{settle / 10:.1f} (largest {max(settled)} ms over "
            f"{len(settled) + never} pastes; never settled in 30 s: {never})"
        )
    else:
        out["610-settle-bound"] = (
            f"1.0 (not measured; the default of D8; never settled in 30 s: {never})"
        )

    # M5 (#610)
    stops = recs.get("stop-paste", [])
    changed = [r for r in stops if r.get("hand_changed") == "yes"]
    late = _nums(changed, "late_ms")  # a late_ms of 0 is a timed 0
    hands = recs.get("hand-hash", [])
    hashes = [
        r["hash"]
        for r in hands
        if r.get("found") == "1" and re.fullmatch(r"[0-9a-f]{12}", r.get("hash", ""))
    ]
    unread = len(hands) - len(hashes)  # not a changed hash: the read proves nothing
    moved = any(h != hashes[0] for h in hashes)
    drain = max(settle, _tenths(0, max(late))) if late else settle
    if not stops:
        words = "M5 not measured"
    else:
        words = f"M5 runs {len(stops)}; hand window changed in {len(changed)}"
        if late:
            words += f"; largest lateness {max(late)} ms"
    if (changed or moved) and not late:
        words += "; late key seen, not timed"
    if unread:
        words += f"; hand reads unreadable: {unread}"
    out["610-drain-wait"] = f"{drain / 10:.1f} ({words})"

    # M4 (#610)
    empty = (recs.get("empty-paste") or [{}])[-1].get("body_equal")
    pasted = {"yes": "nothing pasted", "no": "body changed"}.get(empty, "not measured")
    out["610-empty-paste"] = f"{pasted}; beep {owner.get('beep', 'not recorded')}"

    # M7, M8 (#585)
    paths = {r.get("app"): r for r in recs.get("app-path", [])}
    mail = paths.get("mail")
    read = (recs.get("id-read") or [None])[-1]
    if mail is None and read is None:
        out["585-id-route"] = "not measured"
    else:
        mail, read = mail or {}, read or {}
        started = "no"
        if read.get("mail_running_before") == "yes":
            started = "was running"
        elif read.get("mail_running_after") == "yes":
            started = "yes"
        out["585-id-route"] = (
            f"by_id {mail.get('by_id', 'not measured')}, by_name "
            f"{mail.get('by_name', 'not measured')}, extension processes "
            f"{mail.get('ext_procs', 'not measured')}; id read "
            f"{read.get('id_read', 'not measured')} in {read.get('ms', '?')} ms; "
            f"mail started {started if read else 'not measured'}; consent dialog "
            f"{owner.get('consent_dialog', 'not recorded')}"
        )
    others = []
    for key in ("notes", "messages", "music"):
        rec = paths.get(key, {})
        name = rec.get("by_name", "")
        if not name or name.startswith("ERR"):
            word = "not available"
        elif name == APPS[key][0] + ".app":
            word = "app"
        else:
            word = "extension"
        if rec.get("ext_procs") == "0":
            word += " (no extension process)"
        others.append(f"{key} {word}")
    out["585-other-apps"] = ", ".join(others)

    # M9 (#611)
    stored = (recs.get("stored-diff") or [None])[-1]
    if stored is None:
        out["611-real-mail"] = "not available"
    else:
        line = (
            f"files {stored.get('files', '?')}, differ {stored.get('differ', '?')}, "
            f"skipped {stored.get('skipped_large', '?')}"
        )
        if stored.get("partial") == "yes":
            line += ", partial"
        if (_num(stored.get("differ")) or 0) > 0:
            line += "; classes: " + (
                ", ".join(f"[{label}] {n}" for n, label in classes) or "not recorded"
            )
        out["611-real-mail"] = line
    return [f"{key}: {out[key]}" for key in _KEYS]


def cmd_verdicts(a) -> int:
    for line in verdict_lines(Path(a.results).read_text("utf-8")):
        say(line)
    return 0


# --- offline checks -------------------------------------------------------------------


@contextlib.contextmanager
def _muted():
    global _PRINT
    lines: list[str] = []
    real, _PRINT = _PRINT, lines.append
    try:
        yield lines
    finally:
        _PRINT = real


def _refuses(fn, *args, **kw) -> str:
    try:
        fn(*args, **kw)
    except P.Refuse as e:
        return str(e)
    raise AssertionError("a refusal was expected")


def cmd_selftest(_a) -> int:
    P._selftest_pure()  # the pure checks of the 05.2 probe still hold

    # the summary of a sample list
    s = summarize(
        [(0, False), (20, False), (120, True), (140, True)], [(300, 1), (550, 1)]
    )
    assert s["first_active_ms"] == 120 and s["index_first_1_ms"] == 300, s
    assert s["half"] == "none" and s["active_lost"] == "no" and s["samples"] == 4, s
    s = summarize([(0, False), (20, False)], [(300, 1)])
    assert s["first_active_ms"] == "never" and s["half"] == "active", s
    s = summarize([(0, True), (20, False)], [(300, 2), (550, 1)])
    assert s["half"] == "index" and s["active_lost"] == "yes", s
    assert s["index_first_1_ms"] == 550 and s["index_not_1"] == 1, s
    assert summarize([], [])["half"] == "both"
    assert summarize([(0, True)], [(10, None)])["half"] == "index"

    # the hash, and the other small pure parts
    assert _h("abc") == "ba7816bf8f01" and len(_h("")) == 12
    app = "/System/Applications/Mail.app"
    ps = [
        app + "/Contents/PlugIns/X.appex/Contents/MacOS/X",
        "/System/Applications/Mail.appx/Contents/MacOS/Mail",
        "/usr/sbin/cfprefsd",
    ]
    assert _proc_counts(ps, app) == (False, 1)
    assert _proc_counts([*ps, app + "/Contents/MacOS/Mail"], app) == (True, 1)
    assert _etime_s("01:02") == 62 and _etime_s("1-02:03:04") == 93784
    assert _etime_s("2:03:04") == 7384 and _etime_s("x") is None
    assert _last_part(app + "/Contents/PlugIns/A B.appex/") == "A_B.appex"
    assert _last_part("ERR-1728") == "ERR-1728"
    assert _tenths(20, 116) == 20 and _tenths(20, 1201) == 25
    assert _tenths(10, 500) == 10 and _tenths(10, 501) == 11

    # say() withholds a line with an at sign or a home path
    for bad in ("to=a" + "@" + "x.invalid", "/" + "Users" + "/x/y", str(Path.home())):
        assert _public(f"k={bad}").startswith("withheld:"), bad
    assert _public("settle_ms=12 hash=ba7816bf8f01") == "settle_ms=12 hash=ba7816bf8f01"
    with _muted() as lines:
        say("x" + "@" + "y")
    assert lines == [_public("@")] and "y" not in lines[0]
    assert P.say is say
    # an error line: the exception type and an AppleScript number, nothing else
    osa = "error: RuntimeError: osascript rc=1: 44:61: execution error: Mail got an "
    assert _public(osa + "error: Can't get message Secret. (-1728)") == (
        "error: RuntimeError (-1728)"
    )
    cut = _public("error: TimeoutExpired: Command '['osascript', 'a b', 'MID']' timed")
    assert cut == "error: TimeoutExpired", cut
    assert _public("error: ") == "error: unknown"
    assert _public("discard=error-RuntimeError") == "discard=error-RuntimeError"

    # a refusal or an error with a scratch reply open says so
    def fails(exc, owned=False):
        def fn(_args):
            _SCRATCH.update(open=True, owned=owned)
            if exc:
                raise exc
            return 0

        real, names = _parser, _parser()[1]
        globals()["_parser"] = lambda: (
            argparse.Namespace(parse_args=lambda _argv: argparse.Namespace(fn=fn)),
            names,
        )
        try:
            with _muted() as lines:
                rc = main(["sig-ax"])
        finally:
            globals()["_parser"] = real
            _SCRATCH.update(open=False, owned=False)
        return rc, lines

    assert fails(P.Refuse("why")) == (3, [f"refused: why; {_LEFT}"])
    boom = fails(RuntimeError("osascript rc=1: secret text (-1712)"))
    assert boom == (1, ["error: RuntimeError (-1712)", f"note: {_LEFT}"]), boom
    assert fails(None) == (0, []) and fails(None, True) == (0, [f"note: {_LEFT}"])

    # the key guard refuses an id outside the expected set, and posts nothing
    posted: list = []

    def post(pid, key):
        posted.append((pid, key))

    def before():
        posted.append("before")

    def ids(*found):
        def read():
            posted.append("ids")
            return list(found)

        return read

    def focus_ok():
        posted.append("focus")
        return object()  # the element that the 05.2 focus check returns

    def focus_false():
        posted.append("focus")
        return False

    def focus_refuses():
        posted.append("focus")
        raise P.Refuse("focused element is not inside the probe's window")

    def guard(expected, required, read, focus):
        del posted[:]
        guarded_key(
            expected, required, 1, before, focus=focus, read_ids=read, post=post
        )

    why = _refuses(guard, {7}, {7}, ids(7, 8), focus_ok)
    assert why == "another compose window" and posted == ["ids"], posted
    why = _refuses(guard, {7, 9}, {7, 9}, ids(9), focus_ok)
    assert why == "the scratch reply is not open" and posted == ["ids"], posted
    _refuses(guard, {7}, {7}, ids(), focus_ok)
    assert posted == ["ids"], posted
    # the focus check is the last check: a failed one writes nothing, posts nothing
    why = _refuses(guard, {7}, {7}, ids(7), focus_false)
    assert why == "the focus check failed" and posted == ["ids", "focus"], posted
    _refuses(guard, {7}, {7}, ids(7), focus_refuses)
    assert posted == ["ids", "focus"], posted
    guard({7, 9}, {7}, ids(7), focus_ok)
    assert posted == ["ids", "focus", "before", (1, P._KEY_V)], posted
    for fn in (cmd_paste_cycle, cmd_empty_paste, cmd_stop_paste):
        assert "focus=focus)" in inspect.getsource(fn), fn.__name__
    src = Path(__file__).read_text("utf-8")
    assert src.count("P._key_" + "to_pid") == 1, "one door to a key event"
    assert "P._key_" + "to_pid" in inspect.getsource(guarded_key)

    # each stop holds its continue in a finally
    global _KILL
    sent: list = []
    real, _KILL = _KILL, lambda pid, sig: sent.append((pid, sig))
    try:
        with contextlib.suppress(RuntimeError), mail_stopped(4242, arm=False):
            raise RuntimeError("the body failed")
        assert sent == [(4242, signal.SIGSTOP), (4242, signal.SIGCONT)], sent
        assert not _STOPPED

        def denied(pid, sig):
            if sig == signal.SIGSTOP:
                raise PermissionError
            sent.append((pid, sig))

        _KILL = denied
        del sent[:]
        with contextlib.suppress(P.Refuse), mail_stopped(4242, arm=False):
            raise AssertionError("the block must not run")
        assert sent == [(4242, signal.SIGCONT)] and not _STOPPED
    finally:
        _KILL = real
    assert "finally" in inspect.getsource(mail_stopped)
    for fn in (cmd_stop_paste, cmd_stop_mail):
        assert "mail_stopped(pid)" in inspect.getsource(fn), fn.__name__
    code = src.replace(inspect.getsource(cmd_selftest), "")
    assert len(re.findall(r"signal\.SIG" + "STOP", code)) == 1, "one stop in code"
    assert STOP_S < STOP_MAX_S <= 10.0

    # the armed stop: the detached backstop starts BEFORE the stop signal, and the
    # handlers and the exit hook are registered
    events: list = []
    real_kill, real_popen = _KILL, subprocess.Popen
    real_signal, real_atexit = signal.signal, atexit.register
    _KILL = lambda pid, sig: events.append(("kill", sig))  # noqa: E731
    subprocess.Popen = lambda cmd, **kw: events.append(("popen", cmd[-1], kw))
    signal.signal = lambda sig, fn: events.append(("signal", sig, fn))
    atexit.register = lambda fn: events.append(("atexit", fn))
    try:
        with mail_stopped(4242):
            events.append(("body",))
    finally:
        _KILL, subprocess.Popen = real_kill, real_popen
        signal.signal, atexit.register = real_signal, real_atexit
    kinds = [e[0] for e in events]
    assert kinds.index("popen") < kinds.index("kill") < kinds.index("body"), kinds
    backstop = events[kinds.index("popen")]
    assert backstop[1] == "sleep 10; kill -CONT 4242", backstop
    assert backstop[2]["start_new_session"] is True, backstop
    assert [e[1] for e in events if e[0] == "kill"] == [signal.SIGSTOP, signal.SIGCONT]
    assert ("atexit", _continue_all) in events, kinds
    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        assert ("signal", sig, _on_signal) in events, sig
    assert not _STOPPED
    try:
        _on_signal(signal.SIGTERM, None)
    except SystemExit as e:  # no hard exit: each `finally` still runs
        assert e.code == 128 + signal.SIGTERM
    else:
        raise AssertionError("the handler must raise SystemExit")
    assert "_arm()" in inspect.getsource(main)

    # each forwarded subcommand exists in the 05.2 probe; nothing here can send
    assert FORWARDED == (
        "open-reply",
        "discard",
        "outgoing-ids",
        "clip-hash",
        "drafts-baseline",
        "drafts-since",
    )
    for name in FORWARDED:
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                P.main([name, "--help"])
            except SystemExit as e:
                assert e.code == 0, name
            else:
                raise AssertionError(f"{name}: no such subcommand")
    assert "send" not in (*FORWARDED, *_parser()[1])
    assert "cmd_" + "send" not in src and "P._SE" + "ND" not in src
    with _muted() as lines:
        assert main(["discard", "1"]) == 3
    assert lines == ["refused: discard needs --original"], lines

    # every script: its own timeout, Mail by bundle id, never by name
    scripts = _scripts()
    for name, text in scripts.items():
        assert "with timeout of 120 seconds" in text, name
        assert 'tell application "' not in text, name
        assert not re.search(r"(?i)\bsend\b", text), name
    assert P._OPEN_REPLY.count(_BY_ID) >= 3 and _BY_ID in _ID_READ

    # the rules of `verdicts`, on made-up result files
    def v(text: str) -> dict[str, str]:
        lines = verdict_lines(text)
        assert [ln.split(": ", 1)[0] for ln in lines] == list(_KEYS), lines
        bounds = [
            ln
            for ln in lines
            if re.match(
                r"(607-poll-bound|610-settle-bound|610-drain-wait): \d+\.\d ", ln
            )
        ]
        assert len(bounds) == 3, lines
        return dict(ln.split(": ", 1) for ln in lines)

    def hold(age, active, half="none", front="com.apple.TextEdit"):
        return (
            f"hold-timeline: result trigger_age_ms={age} front_bundle={front} "
            f"first_active_ms={active} index_first_1_ms=300 half={half}\n"
        )

    none = v("")  # no run
    assert none["607-cause"].startswith("not measured;"), none
    assert none["607-poll-bound"] == "2.0 (not measured; the default of D6)"
    assert none["609-signature-in-ax"] == "not available"
    assert none["610-settle-bound"].startswith("1.0 (not measured; the default of D8")
    assert none["610-drain-wait"] == "1.0 (M5 not measured)"
    assert none["610-empty-paste"] == "not measured; beep not recorded"
    assert none["585-id-route"] == "not measured"
    assert none["585-other-apps"].count("not available") == 3
    assert none["611-real-mail"] == "not available"

    late = v("## step d\n" + hold(900, 1201) + "- `" + hold(5000, 116) + "`\n")
    assert late["607-cause"].startswith("late activation; with input 1 of 1 "), late
    assert late["607-poll-bound"].startswith("2.5 (largest 1201 ms"), late
    quiet = v(hold(900, 116) + hold(5200, 90) + hold(3000, 80))
    assert quiet["607-cause"].startswith("not reproduced;"), quiet
    assert "in neither group 1 (trigger_age_ms 3000)" in quiet["607-cause"], quiet
    assert quiet["607-poll-bound"].startswith("2.0 (largest 116 ms"), quiet
    quiet_never = v(hold(900, 116) + hold(5000, "never", "active"))
    assert quiet_never["607-cause"].startswith("not reproduced; with input 1 of 1 ")
    assert "without input 0 of 1;" in quiet_never["607-cause"], quiet_never
    declined = v(hold(900, "never", "active") + hold(5000, 116))
    assert declined["607-cause"].startswith("declined activation; with input 0 of 1")
    assert "half false: active 1, index 0, both 0" in declined["607-cause"]
    index = v(hold(900, 100, "index") + hold(5000, 1500))
    assert index["607-cause"].startswith("index not held;"), index
    only_mail = v(hold(900, 100, front=P.MAIL))  # input, but Mail was in front
    assert only_mail["607-cause"].startswith("not measured;"), only_mail

    def paste(settle):
        return (
            f"paste-cycle: result trigger_age_ms=10 settle_ms={settle} restored=yes\n"
        )

    zero = v(paste("never") + paste("never") + paste("not-run"))
    assert zero["610-settle-bound"] == (
        "1.0 (not measured; the default of D8; never settled in 30 s: 2)"
    ), zero
    some = v(paste(133) + paste(740) + paste("never"))
    assert some["610-settle-bound"] == (
        "1.5 (largest 740 ms over 3 pastes; never settled in 30 s: 1)"
    ), some
    assert some["610-drain-wait"] == "1.5 (M5 not measured)"

    def stop(changed, late_ms):
        return (
            f"stop-paste: result discard=ok hand_changed={changed} late_ms={late_ms}\n"
        )

    key = v(paste(133) + stop("no", "none") + stop("yes", 900))
    assert key["610-drain-wait"] == (
        "1.8 (M5 runs 2; hand window changed in 1; largest lateness 900 ms)"
    ), key
    kept = v(paste(133) + stop("no", "none"))
    assert kept["610-drain-wait"] == "1.0 (M5 runs 1; hand window changed in 0)", kept
    timed0 = v(paste(133) + stop("yes", 0))
    assert timed0["610-drain-wait"] == (
        "1.0 (M5 runs 1; hand window changed in 1; largest lateness 0 ms)"
    ), timed0
    lost = "hand-hash: result found=0 hash=none outgoing_id=unknown\n"
    hand = "hand-hash: result found=1 hash={} outgoing_id=5\n"
    blind = v(stop("no", "none") + hand.format("a" * 12) + lost + lost)
    assert blind["610-drain-wait"] == (
        "1.0 (M5 runs 1; hand window changed in 0; hand reads unreadable: 2)"
    ), blind
    # a malformed value cannot crash the verdicts
    odd = v(
        hold("x", "\u00b2")
        + paste("\u00b2")
        + stop("yes", "-5")
        + stop("yes", "1e3")
        + "stored-diff: result files=\u00b2 differ=many\nid-read: result ms\n"
    )
    assert odd["610-drain-wait"].endswith("; late key seen, not timed)"), odd
    assert odd["611-real-mail"].startswith("files \u00b2, differ many"), odd
    assert _num("\u00b2") is None and _num(None) is None and _num("-1") is None
    assert _num("12") == 12 and _num("0") == 0
    untimed = v(stop("no", "none") + hand.format("a" * 12) + hand.format("b" * 12))
    assert untimed["610-drain-wait"].endswith("; late key seen, not timed)"), untimed
    assert untimed["610-drain-wait"].startswith("1.0 "), untimed

    rest = v(
        "sig-ax: result signature_read=yes in_ax_body=no\n"
        "empty-paste: result body_equal=yes restored=yes\n"
        "owner: beep=no\nowner: consent_dialog=no\n"
        "app-path: result app=mail running=no ext_procs=2 by_name=Q.appex "
        "by_id=Mail.app\n"
        "app-path: result app=notes ext_procs=0 by_name=Notes.app by_id=Notes.app\n"
        "app-path: result app=music ext_procs=1 by_name=M.appex by_id=Music.app\n"
        "id-read: result id_read=ok windows=1 ms=812 mail_running_before=no "
        "mail_running_after=yes\n"
        "stored-diff: result files=9 differ=9 skipped_large=0 partial=no\n"
        "stored-diff: class n=9 label=stale\n"
        "stored-diff: result files=40 differ=2 skipped_large=1 partial=yes\n"
        "stored-diff: class n=2 label=a '<' before the tag's '>'\n"
    )
    assert rest["609-signature-in-ax"] == "no"
    assert rest["610-empty-paste"] == "nothing pasted; beep no"
    assert rest["585-id-route"] == (
        "by_id Mail.app, by_name Q.appex, extension processes 2; id read ok in "
        "812 ms; mail started yes; consent dialog no"
    ), rest
    assert rest["585-other-apps"] == (
        "notes app (no extension process), messages not available, music extension"
    ), rest
    assert rest["611-real-mail"] == (
        "files 40, differ 2, skipped 1, partial; classes: "
        "[a '<' before the tag's '>'] 2"
    ), rest
    unread = v("sig-ax: result signature_read=no in_ax_body=no\n")
    assert unread["609-signature-in-ax"] == "not available"
    assert v("empty-paste: result body_equal=no\n")["610-empty-paste"].startswith(
        "body changed;"
    )

    say(f"selftest ok forwarded={len(FORWARDED)} scripts={len(scripts)}")
    return 0


def cmd_compile(_a) -> int:
    """osacompile on each script: no Apple Event, no app is started."""
    scripts = _scripts()
    failed = 0
    with tempfile.TemporaryDirectory(prefix="p0512-") as d:
        for name, text in scripts.items():
            src = Path(d) / f"{name}.applescript"
            src.write_text(text, "utf-8")
            r = subprocess.run(
                ["/usr/bin/osacompile", "-o", str(Path(d) / f"{name}.scpt"), str(src)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if r.returncode:
                failed += 1
                err = r.stderr.replace(str(src), name).strip()[:160]
                say(f"compile: {name} rc={r.returncode} {err}")
    say(f"compile: scripts={len(scripts)} failed={failed}")
    return 1 if failed else 0


# --- device helpers (PyObjC loads inside the subcommand that needs it) ----------------


def _need_ax() -> None:
    if not P._trusted():
        raise P.Refuse("Accessibility is off for this process")


def _mail_active(pid: int) -> bool:
    app = P._bind()["AXUIElementCreateApplication"](pid)
    return bool(P._ax(app, "AXFrontmost"))  # unreadable: not active


def _trigger_age_ms() -> int:
    fn = P._cg().CGEventSourceSecondsSinceLastEventType
    fn.restype = ctypes.c_double
    fn.argtypes = [ctypes.c_int32, ctypes.c_uint32]
    return _ms(fn(0, 0xFFFFFFFF))  # the combined session state, any input event


def _trigger(cmd: str, after: int) -> dict:
    """The audible countdown (one sound each second), then the condition as read."""
    if not 0 <= after <= 30:
        raise P.Refuse("--after must be 0 to 30")
    for _ in range(after):
        try:
            subprocess.Popen(
                ["/usr/bin/afplay", _SOUND],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            import AppKit

            AppKit.NSBeep()
        time.sleep(1.0)
    res = {
        "trigger_age_ms": _trigger_age_ms(),
        "front_bundle": P._frontmost_bundle() or "none",
    }
    say(f"{cmd}: at-trigger {_kv(res)}")
    return res


def _ps(*args: str) -> str:
    r = subprocess.run(
        ["/bin/ps", *args],
        capture_output=True,
        text=True,
        timeout=10,
        env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"},
    )
    return r.stdout


def _app_procs(name: str) -> tuple[bool, int]:
    lines = [ln.strip() for ln in _ps("-axww", "-o", "comm=").splitlines()]
    return _proc_counts(lines, f"/System/Applications/{name}.app")


def _bring(wid: int, pid: int) -> None:
    """One activation script (activate, window to index 1), then a bounded wait on
    the Accessibility read only. No refusal here: the focus check decides."""
    P._osa(P._ACTIVATE, str(wid))
    end = time.monotonic() + 2.0
    while time.monotonic() < end and not _mail_active(pid):
        time.sleep(0.02)


def _open_reply(mid: str, account: str, path: str) -> tuple[int, int]:
    """open-reply of the 05.2 probe; the ids come from the lines it printed."""
    start = len(_LOG)
    ns = argparse.Namespace(mid=mid, account=account, path=path, all="0")
    rc = P.cmd_open_reply(ns)
    text = "\n".join(_LOG[start:])
    win = re.search(r"^window-id: (\d+) ", text, re.M)
    out = re.search(r"^open-reply: outgoing_id=(\d+)$", text, re.M)
    if rc or not win or not out:
        raise P.Refuse("no scratch reply was bound; close a leftover window by hand")
    return int(win[1]), int(out[1])


def _discard(oid: int, original: list[str]) -> str:
    """The guarded discard: only a reply to the scratch original. Never raises."""
    try:
        P._guard(str(oid), original)
        out = P._osa(P._DISCARD, str(oid))
    except P.Refuse:
        return "refused-not-probe"
    except Exception as e:  # noqa: BLE001 - the clipboard restore must still run
        return f"error-{type(e).__name__}"
    return "ok" if out == "dead-1728" else out or "empty"


class _Clip:
    """The general pasteboard, borrowed: a complete snapshot or a refusal."""

    def __init__(self) -> None:
        import AppKit

        self.pb = AppKit.NSPasteboard.generalPasteboard()
        self.snap, bad = P._snapshot(self.pb)
        self.cc0 = int(self.pb.changeCount())
        P._require_snapshot(self.snap, bad, self.cc0, len(self.pb.types() or []))
        self.base = P._hash_items(self.snap)
        self.mine: int | None = None

    def fresh(self) -> None:
        if int(self.pb.changeCount()) != self.cc0:
            raise P.Refuse("clipboard changed after the snapshot; run again")

    def write(self, text: str | None) -> None:
        """The marker as a transient item; None empties the pasteboard."""
        self.fresh()
        try:
            if text is None:
                self.pb.clearContents()
            else:
                P._write_marker(self.pb, text)
        except BaseException:
            if int(self.pb.changeCount()) == self.cc0 + 1:
                self.mine = self.cc0 + 1  # a half-done write is ours to restore
            raise
        self.mine = int(self.pb.changeCount())

    def restore(self) -> str:
        if self.mine is None:
            return "not-written"
        if int(self.pb.changeCount()) != self.mine:
            return "no"  # a newer copy by the owner stays
        P._restore(self.pb, self.snap)
        items, bad = P._snapshot(self.pb)
        return _yn(bad == 0 and P._hash_items(items) == self.base)


def _find_role(root, role: str, budget: int = 1500):
    """The first element with that role under `root` (bounded walk, AX reads only)."""
    queue = [root]
    while queue and budget > 0:
        budget -= 1
        node = queue.pop(0)
        if P._ax(node, "AXRole") == role:
            return node
        queue.extend(P._ax(node, "AXChildren") or [])
    return None


def _hand_bodies(pid: int) -> list:
    """The body elements of Mail's windows that hold the hand marker."""
    app = P._bind()["AXUIElementCreateApplication"](pid)
    hits = []
    for win in P._ax(app, "AXWindows") or []:
        area = _find_role(win, "AXWebArea")
        if area is not None and MARKER_HAND in P._read_body(area)[0]:
            hits.append(area)
    return hits


def _body_hash(el) -> str:
    """12 hex of the body text, or "" when the body did not read."""
    body = P._fold(P._read_body(el)[0])
    return _h(body) if body else ""


# --- device subcommands ---------------------------------------------------------------


def cmd_app_path(_a) -> int:
    for key, (name, bundle_id) in APPS.items():
        res = {"app": key}
        running, res["ext_procs"] = _app_procs(name)
        res = {"app": key, "running": _yn(running), "ext_procs": res["ext_procs"]}
        for label, script, arg in (
            ("by_name", _PATH_BY_NAME, name),
            ("by_id", _PATH_BY_ID, bundle_id),
        ):
            try:
                res[label] = _last_part(P._osa(script, arg))
            except Exception as e:  # noqa: BLE001 - the next app still runs
                res[label] = f"ERR-{type(e).__name__}"
            time.sleep(1.0)  # a started app needs a moment to show in the table
            state = "running_mid" if label == "by_name" else "running_after"
            res[state] = _yn(_app_procs(name)[0])
        say(f"app-path: result {_kv(res)}")
    return 0


def cmd_id_read(_a) -> int:
    res = {"id_read": "err:0", "windows": "-", "ms": 0}
    res["mail_running_before"] = _yn(_app_procs("Mail")[0])
    t0 = time.monotonic()
    try:
        out = P._osa(_ID_READ)
    except Exception as e:  # noqa: BLE001 - a verdict, never a trace
        out = f"ERR{type(e).__name__}"
    res["ms"] = _ms(time.monotonic() - t0)
    if out.startswith("ok"):
        res["id_read"], res["windows"] = "ok", out[2:] or "-"
    else:
        res["id_read"] = "err:" + out.removeprefix("ERR")
    time.sleep(1.0)
    res["mail_running_after"] = _yn(_app_procs("Mail")[0])
    say(f"id-read: result {_kv(res)}")
    return 0


def cmd_hold_timeline(a) -> int:
    _SCRATCH["open"] = True  # the window of `open-reply` stays open by design
    _need_ax()
    pid = P._mail_pid()
    res = _trigger("hold-timeline", a.after)
    res["active_before"] = _yn(_mail_active(pid))
    index: list[tuple[int, int | None]] = []
    box: dict = {}
    t0 = time.monotonic()

    def scripts() -> None:  # the script calls, off the sampling thread
        try:
            P._osa(P._ACTIVATE, str(a.window_id))
        except Exception as e:  # noqa: BLE001 - reported in the result line
            box["activate_ms"] = f"error-{type(e).__name__}"
            return
        box["activate_ms"] = _ms(time.monotonic() - t0)
        while time.monotonic() - t0 < HOLD_S:
            started = time.monotonic()  # never two reads closer than 250 ms
            try:
                out = P._osa(P._WINDOW_INDEX, str(a.window_id))
            except Exception:  # noqa: BLE001 - an unreadable index is not 1
                out = ""
            index.append(
                (_ms(time.monotonic() - t0), int(out) if out.isdigit() else None)
            )
            _sleep_until(started + 0.25)

    worker = threading.Thread(target=scripts, daemon=True)
    worker.start()
    app = P._bind()["AXUIElementCreateApplication"](pid)
    active: list[tuple[int, bool]] = []
    while (t := time.monotonic() - t0) < HOLD_S:
        active.append((_ms(t), bool(P._ax(app, "AXFrontmost"))))
        time.sleep(0.02)
    worker.join(P._OSA_TIMEOUT + 10)
    res["activate_ms"] = box.get("activate_ms", "timeout")
    res.update(summarize(active, list(index)))
    say(f"hold-timeline: result {_kv(res)}")
    return 0


def cmd_paste_cycle(a) -> int:
    _need_ax()
    pid = P._mail_pid()
    original = [a.mid, a.account, a.path]
    wid, oid = _open_reply(*original)
    _SCRATCH.update(open=True, owned=True)

    def focus():
        return P._focus_check(pid, wid, _ROLES)

    res: dict = {
        "trigger_age_ms": "-",
        "front_bundle": "-",
        "mail_cpu": "-",
        "mail_uptime_s": "-",
        "mail_active": "-",
        "settle_ms": "not-run",
        "samples": 0,
    }
    clip = None
    try:
        res.update(_trigger("paste-cycle", a.after))
        cpu, _, etime = _ps("-o", "%cpu=,etime=", "-p", str(pid)).strip().partition(" ")
        res["mail_cpu"] = cpu or "-"
        res["mail_uptime_s"] = _etime_s(etime) if etime.strip() else "-"
        clip = _Clip()
        _bring(wid, pid)
        res["mail_active"] = _yn(_mail_active(pid))
        el = focus()  # the body of THIS window has focus
        pre = P._squash(P._read_body(el)[0])
        write = lambda: clip.write(MARKER_PASTE)  # noqa: E731
        guarded_key({oid}, {oid}, pid, write, focus=focus)
        t0 = time.monotonic()
        res["settle_ms"] = "never"
        while time.monotonic() - t0 < SETTLE_MAX_S:
            body = P._read_body(el)[0]
            res["samples"] += 1
            if P._starts_with_marker(body, MARKER_PASTE) and P._squash(body) != pre:
                res["settle_ms"] = _ms(time.monotonic() - t0)
                break
            time.sleep(0.01)
    finally:
        res["discard"] = _discard(oid, original)  # BEFORE the clipboard restore
        _SCRATCH["open"] = res["discard"] != "ok"
        res["window_left"] = _yn(_SCRATCH["open"])
        res["restored"] = clip.restore() if clip else "not-written"
        say(f"paste-cycle: result {_kv(res)}")
    return 0


def cmd_empty_paste(a) -> int:
    _SCRATCH["open"] = True
    _need_ax()
    pid = P._mail_pid()
    expected = {a.outgoing_id}  # exactly the scratch reply of step D

    def focus():
        return P._focus_check(pid, a.window_id, _ROLES)

    clip = _Clip()
    _bring(a.window_id, pid)
    el = focus()
    before = P._fold(P._read_body(el)[0])
    res = {
        "body_equal": "not-run",
        "body_chars": len(before),
        "hash_before": _h(before),
        "hash_after": "-",
    }
    try:
        guarded_key(expected, expected, pid, lambda: clip.write(None), focus=focus)
        time.sleep(2.0)
        after = P._fold(P._read_body(el)[0])
        res["hash_after"] = _h(after)
        res["body_equal"] = _yn(after == before) if before and after else "unreadable"
    finally:
        res["restored"] = clip.restore()
        say(f"empty-paste: result {_kv(res)}")
    return 0


def cmd_stop_paste(a) -> int:
    _SCRATCH.update(open=True, owned=True)
    _need_ax()
    pid = P._mail_pid()
    say(f"stop-paste: mail_pid={pid}")  # first: the hand recovery is kill -CONT <n>
    oid, hand = int(a.oid), int(a.hand)
    if oid == hand:
        raise P.Refuse("the scratch reply and the hand window are the same")
    P._guard(a.oid, a.original)  # while Mail still answers

    def focus():
        return P._focus_check(pid, a.window_id, _ROLES)

    _bring(a.window_id, pid)
    el = focus()
    hands = _hand_bodies(pid)
    if len(hands) != 1:
        raise P.Refuse("the hand window was not found")
    h0 = _body_hash(hands[0])
    if not h0:
        raise P.Refuse("the hand window did not read")
    clip = _Clip()
    res: dict = {
        "mail_pid": pid,
        "stopped_ms": 0,
        "discard": "not-run",
        "discard_ms": "-",
        "key_seen_ms": "none",
        "hand_changed": "no",
        "late_ms": "none",
    }
    done: dict = {}

    def discard() -> None:  # started during the stop; it answers after the continue
        try:
            done["out"] = P._osa(P._DISCARD, a.oid)
        except Exception as e:  # noqa: BLE001 - reported in the result line
            done["out"] = f"error-{type(e).__name__}"
        done["t"] = time.monotonic()

    worker = threading.Thread(target=discard, daemon=True)
    try:
        with contextlib.ExitStack() as stack:
            times: dict = {}

            def stop_and_mark() -> None:  # the focus check ran right before
                stack.enter_context(mail_stopped(pid))
                times["stop"] = time.monotonic()
                clip.write(MARKER_PASTE)  # a moved clipboard refuses: no key

            both = {oid, hand}
            guarded_key(both, both, pid, stop_and_mark, focus=focus)
            worker.start()
            _sleep_until(times["stop"] + STOP_S)
        t_cont = time.monotonic()  # the stack sent the continue signal
        res["stopped_ms"] = _ms(t_cont - times["stop"])
        changed_at = None
        while time.monotonic() - t_cont < 30.0:  # Accessibility reads only
            now = time.monotonic()
            unseen = res["key_seen_ms"] == "none" and "t" not in done
            if unseen and MARKER_PASTE in P._read_body(el)[0]:
                res["key_seen_ms"] = _ms(now - t_cont)
            if changed_at is None and _body_hash(hands[0]) not in ("", h0):
                changed_at = now
            if "t" in done and (changed_at or now - done["t"] > 5.0):
                break
            time.sleep(0.02)
        worker.join(P._OSA_TIMEOUT + 10)
        out = done.get("out", "timeout")
        res["discard"] = "ok" if out == "dead-1728" else out or "empty"
        _SCRATCH["open"] = res["discard"] != "ok"
        if "t" in done:
            res["discard_ms"] = _ms(done["t"] - t_cont)
        h1 = _body_hash(hands[0])
        res["hand_changed"] = _yn(h1 != h0) if h1 else "unreadable"
        if changed_at is not None and "t" in done and h1 not in ("", h0):
            res["late_ms"] = max(0, _ms(changed_at - done["t"]))
    finally:
        _continue_all()  # SIGCONT again: never leave Mail stopped
        res["window_left"] = _yn(_SCRATCH["open"])
        res["restored"] = clip.restore()
        say(f"stop-paste: result {_kv(res)}")
    return 0


def cmd_sig_ax(a) -> int:
    _SCRATCH["open"] = True
    _need_ax()
    pid = P._mail_pid()
    sig = P._parse_sig_read(P._osa(_SIG_OF, a.oid) + P._RS)[0] or ""
    _bring(a.window_id, pid)
    el = P._focus_check(pid, a.window_id, _ROLES)
    body, via = P._read_body(el)
    want, have = P._alnum(sig), P._alnum(body)
    res = {
        "signature_read": _yn(want),
        "in_ax_body": _yn(want and want in have),
        "sig_chars": len(want),
        "body_chars": len(have),
        "via": via,
    }
    say(f"sig-ax: result {_kv(res)}")
    return 0


def cmd_hand_hash(_a) -> int:
    _need_ax()
    hands = _hand_bodies(P._mail_pid())
    ids = _outgoing_ids()
    one = len(hands) == 1
    res = {
        "found": len(hands),
        "hash": (_body_hash(hands[0]) or "none") if one else "none",
        "outgoing_id": ids[0] if one and len(ids) == 1 else "unknown",
        "outgoing_count": len(ids),
    }
    say(f"hand-hash: result {_kv(res)}")
    return 0


def cmd_stop_mail(a) -> int:
    if not 0 < a.seconds <= STOP_MAX_S:
        raise P.Refuse("seconds must be above 0 and at most 10")
    if not 0 < a.wait <= 300:
        raise P.Refuse("--wait must be above 0 and at most 300")
    pid = P._mail_pid()
    say(f"stop-mail: mail_pid={pid}")  # first: the hand recovery is kill -CONT <n>

    def windows() -> set[int]:  # the window list only: no event reaches Mail
        return {
            w["num"] for w in P._cg_windows() if w["pid"] == pid and w["layer"] == 0
        }

    res = {"mail_pid": pid, "window_seen": "no", "waited_ms": 0, "stopped_ms": 0}
    base = windows()
    t0 = time.monotonic()
    while time.monotonic() - t0 < a.wait:
        if windows() - base:
            res["window_seen"] = "yes"
            break
        time.sleep(0.02)
    res["waited_ms"] = _ms(time.monotonic() - t0)
    try:
        if res["window_seen"] == "yes":
            t1 = time.monotonic()
            with mail_stopped(pid):
                _sleep_until(t1 + a.seconds)
            res["stopped_ms"] = _ms(time.monotonic() - t1)
    finally:
        _continue_all()  # SIGCONT again: never leave Mail stopped
        say(f"stop-mail: result {_kv(res)}")
    return 0


def _markup(msg) -> str:
    """The HTML of a message, as split_quote reads it."""
    markup = ""
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            try:
                markup += part.get_content()
            except (LookupError, ValueError):
                continue
    return markup


def cmd_stored_diff(a) -> int:
    import email
    import email.policy

    from macos_apps_mcp.adapters.mail_index import emlx_payload

    strips = _load(HERE / "split_quote_linear.py", "split_quote_linear")
    if not re.fullmatch(r"[0-9A-Za-z-]{1,64}", a.account):
        raise P.Refuse("the account id has an unexpected form")
    if not (math.isfinite(a.budget) and a.budget > 0):
        raise P.Refuse("--budget must be a number above 0")
    budget = min(a.budget, 600.0)
    try:
        from macos_apps_mcp.adapters.mailbox_url import SENT_LEAVES
    except ImportError:  # an older package: the four common names
        SENT_LEAVES = ("Sent", "Sent Messages", "Sent Mail", "Sent Items")
    wanted = {n.casefold() for n in (*SENT_LEAVES, "Drafts", "Draft")}
    t0 = time.monotonic()
    stores = sorted(
        Path.home().glob("Library/Mail/V*"),
        key=lambda p: int(p.name[1:]) if p.name[1:].isdigit() else -1,
    )
    account = stores[-1] / a.account if stores else None
    boxes: list[Path] = []
    if account is not None and account.is_dir():
        # the mailbox tree is nested *.mbox folders: never walk the message folders
        for folder, names, _files in os.walk(account):
            names[:] = [n for n in names if n.endswith(".mbox")]
            boxes += [  # the folder NAME, never a part of it
                Path(folder) / n
                for n in names
                if n.removesuffix(".mbox").casefold() in wanted
            ]
    res = {
        "files": 0,
        "parsed": 0,
        "html": 0,
        "differ": 0,
        "skipped_large": 0,
        "errors": 0,
        "mailboxes": len(boxes),
        "partial": "no",
    }
    classes: dict[str, int] = {}
    seen: set[Path] = set()
    for box in boxes:
        for f in box.rglob("*.emlx"):
            if time.monotonic() - t0 > budget:
                res["partial"] = "yes"
                break
            if f in seen:
                continue
            seen.add(f)
            res["files"] += 1
            try:
                raw = emlx_payload(f.read_bytes())
                if not raw:
                    continue
                msg = email.message_from_bytes(raw, policy=email.policy.default)
                markup = _markup(msg)
                new = strips.split_quote(msg, strips.drop_blocks, strips.drop_tags)
                res["parsed"] += 1
                res["html"] += bool(markup)
                if len(markup) > LARGE_BODY:
                    res["skipped_large"] += 1  # the old strip is quadratic
                    continue
                old = strips.split_quote(msg, strips.old_blocks, strips.old_tags)
                if old != new:
                    res["differ"] += 1
                    for label in strips._class_of(markup).split("; "):
                        classes[label] = classes.get(label, 0) + 1
            except Exception:  # noqa: BLE001 - counted, never printed
                res["errors"] += 1
        if res["partial"] == "yes":
            break
    res["elapsed_s"] = round(time.monotonic() - t0)
    say(f"stored-diff: result {_kv(res)}")
    for label, n in sorted(classes.items(), key=lambda kv: -kv[1]):
        say(f"stored-diff: class n={n} label={label}")
    if not boxes:
        raise P.Refuse("no Sent or Drafts mailbox was found for that account")
    return 0


# --- main -----------------------------------------------------------------------------


def _parser() -> tuple[argparse.ArgumentParser, list[str]]:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    names: list[str] = []

    def add(name, fn, *pos):
        sp = sub.add_parser(name)
        for x in pos:
            sp.add_argument(x)
        sp.set_defaults(fn=fn)
        names.append(name)
        return sp

    original = {"nargs": 3, "metavar": ("MID", "ACCOUNT", "PATH")}
    add("selftest", cmd_selftest)
    add("compile", cmd_compile)
    add("verdicts", cmd_verdicts, "results")
    add("app-path", cmd_app_path)
    add("id-read", cmd_id_read)
    ht = add("hold-timeline", cmd_hold_timeline)
    ht.add_argument("window_id", type=int)
    ht.add_argument("--after", type=int, default=0)
    pc = add("paste-cycle", cmd_paste_cycle, "mid", "account", "path")
    pc.add_argument("--after", type=int, default=0)
    ep = add("empty-paste", cmd_empty_paste)
    ep.add_argument("window_id", type=int)
    ep.add_argument("--outgoing-id", type=int, required=True)
    sp = add("stop-paste", cmd_stop_paste)
    sp.add_argument("window_id", type=int)
    sp.add_argument("oid")
    sp.add_argument("--hand", required=True)
    sp.add_argument("--original", required=True, **original)
    sa = add("sig-ax", cmd_sig_ax)
    sa.add_argument("window_id", type=int)
    sa.add_argument("oid")
    sd = add("stored-diff", cmd_stored_diff)
    sd.add_argument("--account", required=True)
    sd.add_argument("--budget", type=float, default=120.0)
    add("hand-hash", cmd_hand_hash)
    sm = add("stop-mail", cmd_stop_mail)
    sm.add_argument("seconds", type=float)
    sm.add_argument("--wait", type=float, default=60.0)
    return p, names


def main(argv: list[str] | None = None) -> int:
    if argv is None:  # a real run: a terminated probe still runs each `finally`
        _arm()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in FORWARDED:
        if argv[0] == "discard" and "--original" not in argv:
            say("refused: discard needs --original")
            return 3
        return P.main(argv)  # the 05.2 probe parses, runs and prints (through say)
    args = _parser()[0].parse_args(argv)
    _SCRATCH.update(open=False, owned=False)
    try:
        rc = args.fn(args)
    except P.Refuse as e:
        say(f"refused: {e}" + (f"; {_LEFT}" if _SCRATCH["open"] else ""))
        return 3
    except SystemExit:  # a signal: each `finally` of the subcommand ran
        if _SCRATCH["open"]:
            say(f"note: {_LEFT}")
        raise
    except Exception as e:  # noqa: BLE001 - a probe prints a verdict, never a trace
        say(f"error: {type(e).__name__}: {str(e)[:300]}")
        if _SCRATCH["open"]:
            say(f"note: {_LEFT}")
        return 1
    if _SCRATCH["open"] and _SCRATCH["owned"]:
        say(f"note: {_LEFT}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
