---
status: diagnosed
trigger: "clipboard-chromium-url-hash-mismatch: Reply insertion preserves every clipboard type."
created: 2026-11-14T00:00:00Z
updated: 2026-11-14T00:45:00Z
---

## Current Focus

bug_class: Heisenbug (one run of many; six later comparisons passed) — SBFL skipped
hypothesis: CONFIRMED (category b, outside change). An outside pasteboard write happened between the UAT "before" clip-hash and the "after" clip-hash. The product restore is byte-identical to its own snapshot, so it cannot change one type and keep the others.
test: done — code read, Chromium source read, real `_Clipboard` round trip on a private pasteboard, unit tests
expecting: n/a
next_action: Return ROOT CAUSE FOUND to the caller. Optional owner-side confirmation: compare `changeCount` in the before and after clip-hash JSON files of the failing Spotlight run (git-ignored evidence folder, not read in this session).

reasoning_checkpoint:
  hypothesis: "The source-URL mismatch in the UAT Spotlight run comes from a pasteboard write by another process (a Chromium-family app copying the same text again from the same frame after its main-frame URL changed, or a clipboard-history re-insertion of that copy) in the owner-interaction gap between the 'before' clip-hash and the call, or during the paste window; it is not a change made by `_Clipboard.restore`."
  confirming_evidence:
    - "The real `_Clipboard.snapshot -> write_text -> restore -> snapshot` on a private unique-name AppKit pasteboard, with a Chromium-shaped item (text via setString, `org.chromium.source-url` via setString, pickled token via setData), is per-type SHA-256 equal and stable on re-read."
    - "A second Chromium-shaped copy with the same text and token and a changed main-frame URL reproduces the exact UAT signature: text equal, token equal, source-url different."
    - "Chromium (clipboard_mac.mm, clipboard_types.cc) writes source-url eagerly from the MAIN FRAME's last committed URL and the token from the copying frame, and never rewrites the pasteboard on its own after another process writes it."
    - "Text and token hashes matched after the call, so the after state is not our transient marker: either our restore ran (then after == our snapshot, so the snapshot already differed from the before hash), or the change count moved past our write (an outside write, restore skipped by design)."
  falsification_test: "In the failing run's clip-hash JSON files, after.changeCount - before.changeCount == 2 (one write_text, one restore, as measured) together with a source-url mismatch would contradict 'the restore ran and an outside write preceded the snapshot'; it would then mean the restore was skipped because of an outside write during the paste window (still outside). Only a delta of exactly 2 WITH evidence that no other process wrote (impossible to show from the files) would reopen a product defect. A real-Chromium round trip on the device that differs would falsify the byte-identity claim."
  fix_rationale: "No product fix to the save/restore. The test procedure must make an outside write visible: compare changeCount deltas, take the before hash after the owner's setup action, and repeat a mismatching run once with a disposable clipboard."
  blind_spots: "The round trip ran on a private pasteboard with a synthetic Chromium-shaped item, not on the general pasteboard with a real Chromium copy (forbidden here). The git-ignored evidence files (changeCount values, the exact sequence of the repeated Spotlight check) were not read. Which outside actor wrote (owner re-copy in a Chromium/Electron app, Spotlight clipboard history, a clipboard manager, Universal Clipboard) is not identified."
  candidate_causes:
    - "code: `_Clipboard.restore` re-encodes a setString-written custom type (eliminated by the round trip)"
    - "code: the restore is skipped wrongly and the marker stays (eliminated: text hash matched; the marker would have changed it)"
    - "environment: an outside pasteboard write (Chromium re-copy after a URL change, clipboard-history re-insert) in the owner-interaction gap (supported)"
    - "data/procedure: the 'after' file compared against a 'before' file from an earlier attempt of the repeated Spotlight check (possible; same category b; not checkable from tracked files)"
  and_gate: "yes — the mismatch needs BOTH an outside write of the same text from the same frame with a different URL AND a procedure whose comparison ignores changeCount and whose before hash precedes an owner action; either alone does not give a recorded product failure."

## Symptoms

expected: Every clipboard type has the same hash before and after a reply insertion.
actual: A Chromium source-URL metadata hash differed; the plain-text hash matched. (UAT observed: the Chromium source-URL hash differed in one Spotlight run; the text hash matched.)
errors: None reported
reproduction: Test 4 in UAT (Phase 05.2, plan 05.2-16 device acceptance, 2026-11-03)
started: Discovered during UAT

## Eliminated

- hypothesis: H1 (product) — `_Clipboard.restore` writes `org.chromium.source-url` with different bytes than Chromium stored (Chromium uses setString:forType:, the restore uses setData:forType:)
  evidence: The real `_Clipboard` methods round-tripped a Chromium-shaped item on a private unique-name AppKit pasteboard; every type's SHA-256 was equal after the restore and on a re-read.
  timestamp: 2026-11-14T00:30:00Z

- hypothesis: H2 (product) — the restore is skipped when it should run, leaving the borrowed item
  evidence: The after state had the original text and token hashes; the borrowed item holds the reply text and the transient/concealed types, so the text hash would differ. `test_compose_insert_keeps_a_newer_user_copy` and the restore-order tests pass (15 clipboard tests).
  timestamp: 2026-11-14T00:32:00Z

- hypothesis: H3 (product) — the restore drops, reorders or renames a type or an item
  evidence: Code read: every type of every item is saved as bytes in insertion order and written back to one new item per saved item; the probe compares per-type hashes sorted by type, so order cannot cause a mismatch; an unreadable type refuses before any write. The round trip kept all three types.
  timestamp: 2026-11-14T00:33:00Z

- hypothesis: H4 (outside, Chromium) — Chromium serves source-url lazily or rewrites it after another process writes the pasteboard
  evidence: Chromium main writes source-url with `setString:forType:` at copy time (no data provider) and `ClipboardChanged` only notifies observers. Chromium cannot change the bytes our restore wrote.
  timestamp: 2026-11-14T00:25:00Z

## Evidence

- timestamp: 2026-11-14T00:05:00Z
  checked: Knowledge base (.planning/debug/knowledge-base.md)
  found: The file does not exist; no resolved sessions. No known-pattern candidate.
  implication: Investigate from first principles.

- timestamp: 2026-11-14T00:10:00Z
  checked: macos_apps_mcp/runtime.py `_Clipboard` (snapshot, write_text, restore) and `compose_insert`
  found: snapshot reads `item.dataForType_(t)` for every type of every item into ordered dicts (bytes); restore builds one NSPasteboardItem per saved item and calls `setData_forType_` with the SAME bytes for the SAME types in the SAME order, then `clearContents` + `writeObjects_`. No type is filtered, renamed or re-encoded. An incomplete snapshot refuses. The change count is read BEFORE the snapshot and checked again as the last step before the write; the restore runs only when the change count still equals the value right after OUR write (a newer copy by someone else is kept, not overwritten).
  implication: By construction the restore is byte-identical to the product's own snapshot. A per-type difference requires either (i) the product's snapshot differing from the "before" clip-hash snapshot (a pasteboard write between the two), or (ii) a write after our restore / instead of our restore, or (iii) AppKit changing bytes on a setString-vs-setData round trip (tested below).

- timestamp: 2026-11-14T00:15:00Z
  checked: 05.2-proto/reply_gui_probe.py `cmd_clip_hash`, `_clip_equal` (the UAT's `P clip-hash` tool)
  found: clip-hash reads the general pasteboard with the same API (dataForType_ per type), hashes per item per type (sorted), records `changeCount`, and `--against` compares only `items` (and `unreadable`), NOT `changeCount`. It is a separate process from the daemon; the "before" file is taken by hand right before each check, then the owner sets up the check (here: opens Spotlight), then the call runs, then the "after" file is taken.
  implication: Any pasteboard write in the gap "before clip-hash -> product snapshot" is invisible to the product guard (the product saves the newer state) and shows as a mismatch. The recorded changeCount values in the before/after JSON files can tell how many writes happened in the window; the comparison ignores them.

- timestamp: 2026-11-14T00:20:00Z
  checked: Chromium source, ui/base/clipboard/clipboard_mac.mm (main) and content/public/browser/clipboard_types.cc
  found: Per copy, Chromium writes eagerly (no lazy data provider): the text types, `org.chromium.source-url` = `[pasteboard setString:data_src->GetURL()->spec() forType:...]` where the URL is the MAIN FRAME's last committed URL (`AddSourceDataToClipboardWriter` -> `SetDataSourceURL(rfh.GetMainFrame()->GetLastCommittedURL(), ...)`), and `org.chromium.internal.source-rfh-token` = the pickled GlobalRenderFrameHostToken of the copying frame. Chromium only READS the pasteboard on changeCount changes (`ClipboardChanged` notifies, never rewrites).
  implication: Same text + same frame token + different source URL is the exact signature of a SECOND copy of the same text from the same frame (same RenderFrameHost) after the main frame's URL changed (a same-document navigation such as a route, query or fragment change keeps the frame token). Chromium does not rewrite the pasteboard on its own after our restore.

- timestamp: 2026-11-14T00:30:00Z
  checked: The REAL `runtime._Clipboard` methods (instance built with `object.__new__`, `_pb` = `NSPasteboard.pasteboardWithUniqueName()`, released afterwards; the general pasteboard never referenced) on a Chromium-shaped item: plain text via setString, `org.chromium.source-url` via setString, `org.chromium.internal.source-rfh-token` via setData (40 synthetic bytes). Script in /tmp, run with `uv run python`.
  found: types kept = [public.utf8-plain-text, org.chromium.source-url, org.chromium.internal.source-rfh-token]; round trip equal = True; re-read stable = True; changeCount steps: write_text +1, restore +1 (a clean call moves the count by exactly 2). A second Chromium-shaped copy with the same text and token and a different main-frame URL: text equal, token equal, source-url NOT equal; one such copy = +1.
  implication: H1 eliminated. The UAT signature is reproduced exactly by an outside re-copy, not by our restore. A clean call is changeCount +2; any outside write adds at least +1, or makes our restore skip.

- timestamp: 2026-11-14T00:35:00Z
  checked: `uv run pytest -q tests/test_runtime.py -k "clipboard or pasteboard or snapshot or newer or restore"`
  found: 15 passed, including `test_real_clipboard_round_trip_restores_every_item_and_type` and `test_compose_insert_keeps_a_newer_user_copy`.
  implication: The unit contract (restore equals snapshot; a newer outside copy is kept) holds.

- timestamp: 2026-11-14T00:38:00Z
  checked: 05.2-16-PLAN.md Task 2 step G(1) and the procedure header; 05.2-13-HANDOFF.md traps; facts §4e Pasteboard rows; 05.2-16-SUMMARY gap 3
  found: Step G(1) has the owner open Spotlight "just before the call", AFTER the "before" clip-hash ("a clipboard hash right before each insert check"). The SUMMARY says the mismatch was in the REPEATED Spotlight check, a later snapshot matched the post-test clipboard, and six later disposable-clipboard comparisons passed. The 05.2-13 handoff already records "The owner's clipboard changes between steps ... take a clipboard hash right before each check". Facts §4e: every device restore (05.2-09 runs 2-13) was hash-equal to its own snapshot; the owner's clipboard changed between runs several times.
  implication: The procedure puts an owner action (opening Spotlight, and in the repeated check, a second setup) between the before hash and the call; the comparison cannot see a write there. "A later snapshot matched the post-test clipboard" fits a stable restore of a state that already differed from the before file.

- timestamp: 2026-11-14T00:40:00Z
  checked: ROADMAP Phase 05.2 criterion 6, REQUIREMENTS FIX-26, STATE (#589)
  found: FIX-26 (#589) = when the paste check fails because the clipboard changed during the call, the refusal says so and asks the user not to copy while a reply runs. Today a change between our write and the restore makes `compose_insert` skip the restore silently; when the paste still settles, the call succeeds and says nothing; when it does not settle, the refusal says only "your text did not appear in the reply within 1 s".
  implication: Same cause class (an outside clipboard write around a reply call) and the same code point (`clip.change_count() == mine` in the `finally`), but a different outcome: #589 is the refusal text; this gap is a SUCCESSFUL call whose test compare saw an outside change. #589's change does not fix this gap. If FIX-26 adds a "the clipboard changed during the call" signal, exposing it on the success path too would make UAT test 4 self-diagnosing.

## Resolution

root_cause: "Not a product defect (category b, outside change). Between the UAT 'before' clip-hash and the 'after' clip-hash of the repeated Spotlight check, another process wrote the general pasteboard with the same text and the same Chromium frame token but a different `org.chromium.source-url` — the signature of a second Chromium-family copy from the same frame after its main-frame URL changed (or a clipboard-history re-insert of that copy). `compose_insert` saved that newer state (the write landed before its own change-count read) and restored it byte-for-byte, or kept it because it landed during the paste window; either way the after state differs from the before file. Contributing (procedure): plan 05.2-16 step G(1) puts the owner's Spotlight action after the before hash, and `clip-hash --against` ignores `changeCount`, so the test cannot tell an outside write from a product change."
fix: "(diagnosis only — no fix applied)"
verification: "Real `_Clipboard` round trip on a private pasteboard: per-type equal, stable; outside re-copy reproduces the exact signature; 15 clipboard unit tests pass."
files_changed: []
