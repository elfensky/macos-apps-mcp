---
status: diagnosed
trigger: "delivered-signature-element-missing: The outgoing signature is comparable with the delivered signature element."
created: 2026-11-14T00:00:00Z
updated: 2026-11-14T00:00:00Z
---

## Current Focus

bug_class: Bohrbug (deterministic). The test tool selects by an element id that Mail's own compose code treats as an internal editing marker.

hypothesis: (b) wrong test assumption, confirmed. `div#AppleMailSignature` is Mail's compose-time editing handle. Mail's compose code strips it as a "Mail attribute" and drops it when the signature text changes. The 05.2-16 delivered HTML had no such element, so `sig_hash.py --eml`, which selects by that id only, printed `eml: none`. No product code reads, writes or depends on the id: the sweep (`_split_quote` + `_is_own`) removes every tag and compares text.

reasoning_checkpoint:
  hypothesis: "The comparison failed because the 05.2-16 method extracted the delivered signature by `id=AppleMailSignature`. That id is a compose-time marker which Mail's own code strips from HTML it copies out of the editor and removes on edit, so a delivered message does not reliably carry it."
  confirming_evidence:
    - "Device: 05.2-16 Gap 2, the outgoing signature read (alnum length 58) and the delivered HTML had no element with that id."
    - "Mail's compose JavaScript (system bundle, read-only): `HtmlIDSignature=\"AppleMailSignature\"` is defined beside internal editing markers; `recursivelyRemoveMailAttributes(true, …)` runs `removeAttribute(\"id\")` on it; a `DOMCharacterDataModified` listener removes the id on the first edit; `_copyHtmlStringFromRange` runs the strip pass on copied-out HTML."
    - "The only device sighting of the id (05.2-13) is not recorded as a delivered message; the 05.2-13 route checks of the delivered message do not look for a signature element."
    - "grep: 0 uses of `AppleMailSignature` in macos_apps_mcp/; the sweep compares tag-stripped text. Unit case `_SIG_WS` (no id) is accepted; the throwaway check gives the same verdict with and without the id."
  falsification_test: "Export the next delivered reply from the signature account and search its `text/html` part for the signature's letters and digits (not the id). If the signature text is absent while the outgoing `message signature` reads, the body lost the signature and the cause is a product or setting defect, not the test method. If a stored Sent copy carries the id, the 'stripped on send' part is wrong (the method stays wrong for the delivered copy)."
  fix_rationale: "Diagnose only. The method must locate the signature by content (the outgoing `content` digest searched in the text before the first `blockquote type=cite`), not by a compose-time id, and must record presence separately from equality."
  blind_spots: "The delivered `.eml` and the private sitting log are outside the worktree and were not read, so it is not proven that the signature TEXT was present in the delivered message. The native send serializer's flag value was not traced; the device result is the proof that the id is absent. Step E read the signature of a different reply window (R2-ON) than the delivered D reply; same account, so the same signature is assumed."
  candidate_causes:
    - "procedure (test method): `sig_hash.py --eml` selects only `[id=AppleMailSignature]`, an id Mail does not keep in delivered HTML. CONFIRMED."
    - "code (product): the quoted-reply path drops, moves or rewrites the signature. ELIMINATED by code reading (no Cmd-A, no content/signature write on a quoted reply)."
    - "config (Mail settings): the signature was not in the body (signature None for the reply, or placed below the quote). Not supported: the outgoing `message signature` read with content, and the owner confirmed the settings before D. Not disproven, because the delivered text was not checked by content."
    - "data (Mail behaviour): the delivered signature text differs from `content` by more than white space. Not observable from the record; affects only the sibling's R2, not this gap."
  and_gate: "No. The method's id selector alone explains `eml: none`; it fails whether or not the signature text is present. A second condition (text absent) would change the product verdict, not this gap's cause."

next_action: Diagnosis complete; return ROOT CAUSE FOUND to the caller (goal: find_root_cause_only).

## Symptoms

expected: The outgoing signature can be compared with the delivered signature element.
actual: The delivered HTML had no AppleMailSignature element; comparison was not possible. (UAT observed: the outgoing signature was readable; the delivered HTML had no `AppleMailSignature` element.)
errors: None reported
reproduction: Test 3 in UAT (Phase 05.2, plan 05.2-16 device acceptance, 2026-11-03)
started: Discovered during UAT

## Eliminated

- hypothesis: Our quoted-reply path (reply_all, `include_quote=True`) drops, rewrites or moves Mail's signature, so the delivered message has no signature element.
  evidence: The quoted path only pastes at the caret (Cmd-A runs only for `replace_all`, the no-quote path). `_REPLY_OPEN` only reads `message signature` and its `content`. No reply script writes `content`, `html content` or `message signature`. Nothing in macos_apps_mcp/ adds, strips or reads the id.
  timestamp: 2026-11-14

- hypothesis: The sweep's set-aside rule (`_is_own`/`_has_quote`) needs `div#AppleMailSignature` in the stored message, so a delivered or sent copy without it fails.
  evidence: `_split_quote` removes every tag before the compare; `_is_own` compares text by `_bare`. The `_SIG_WS` unit case (no id) passes, and the throwaway check gives the same verdict with and without the id.
  timestamp: 2026-11-14

## Evidence

- timestamp: 2026-11-14
  checked: 05.2-UAT.md test 3, 05.2-16-SUMMARY Gap 2, 05.2-16-PLAN context ("signature hash script") and Task 2 step E
  found: The test compared two digests. `--outgoing` read `content` of the `message signature` of a scripted reply window opened in step E (R2-ON). `--eml` read the text inside the element whose `id` is `AppleMailSignature` in the `text/html` part of the message delivered in step D, and printed `eml: none` when no such element exists. The outgoing signature read (alnum length 58). The delivered HTML had no element with that id. The method has no fallback that finds the signature text by content.
  implication: `eml: none` proves only that the id is absent. It does not prove that the signature text is absent from the delivered message. The plan did not record whether the signature text was present.

- timestamp: 2026-11-14
  checked: 05.2-15-PLAN context ("Device evidence (05.2-13 sitting log)"), facts §4e `Layout` row, 05.2-13-SUMMARY G4
  found: The only device observation of `div#AppleMailSignature` is from the 05.2-13 sitting: "Mail put the account's signature as `div#AppleMailSignature` between the text and the quote". No tracked record says which stored file showed it. In 05.2-13 the stored files read were the autosaved Drafts copies (deleted by exact id) and the sweep's rows. The delivered message was checked only by the route checks (marker, wrapper, attribution, cid references, text/plain), which do not look at a signature element.
  implication: The assumption "the delivered MIME has `div#AppleMailSignature`" was extrapolated from a compose-time copy, not observed on a delivered message. 05.2-16 is the first check of the delivered MIME, and it refutes the assumption.

- timestamp: 2026-11-14
  checked: Mail's compose code, read-only, no user data (`strings` on /System/Applications/Mail.app/Contents/MacOS/Mail and on MailUI.framework's MailUIWebBundle, the compose WebKit bundle, macOS 27)
  found: (1) The Mail binary holds the literal `<DIV id="AppleMailSignature">`; the compose JavaScript defines `HtmlIDSignature="AppleMailSignature"` beside other internal editing markers (`AppleOriginalContents`, `AppleTemporaryEditingElement`, `ApplePlainTextBody`, `Apple-paste-as-quotation`). (2) `HTMLElement.prototype.recursivelyRemoveMailAttributes(t, …)`: when `t` is true it runs `this.id===HtmlIDSignature && this.removeAttribute("id")` and removes those internal classes. (3) `replaceOldSignatureWithNewSignature` adds a `DOMCharacterDataModified` listener to the signature element that removes its `id` the first time its text changes. (4) The JavaScript calls the strip pass on the quoted original's body (so an earlier signature id in the quote is not taken for the new one). The send-time serializer is native code in the shared cache and was not traced (`_isBeingPreparedForSending` exists in the Mail binary).
  implication: The id is a compose-time handle, which Mail uses to find and replace the signature when the Signature menu changes. Mail's own code strips it as a "Mail attribute", and also drops it when the signature text is edited. An id that Mail strips is not a stable marker of a delivered or sent message. This explains `eml: none` without any product change to the body.

- timestamp: 2026-11-14
  checked: macos_apps_mcp/adapters/mail_reply_cleanup.py `_split_quote` (218), `_bare` (272), `_is_own` (283), `find_own_draft` (323-379); grep `AppleMailSignature` in macos_apps_mcp/
  found: No product code mentions `AppleMailSignature` (0 hits in macos_apps_mcp/). `_split_quote` cuts the HTML at the first `<blockquote`, removes every tag with `<[^>]+>`, unescapes and squashes. `_is_own` then compares the text after the call's text with the signature `content` by `_bare` (NFC, white space and U+FFFC removed). The element id appears only in two test fixtures (`tests/test_mail_reply_cleanup.py:683` `_SIG_HTML`, `tests/test_mail_reply_window.py:36` `SIG_HTML`). The fixture `_SIG_WS` (no id, a link, `&nbsp;`) is already an accepted case.
  implication: The sweep's set-aside rule does not depend on the element. The missing id cannot by itself make `_is_own` fail. Only text that differs from `content` by more than white space, or a signature below the quote, can fail it.

- timestamp: 2026-11-14
  checked: shared-cache compose JavaScript (read-only `strings`, no user data): the Mail framework's editing script
  found: The same script defines `MFHtmlIDSignature="AppleMailSignature"`, `MFHtmlIDLineBreakAtSignature="lineBreakAtBeginningOfSignature"` and `MFHtmlIDLineBreakAtBeginning="lineBreakAtBeginningOfMessage"`. `_locateSignatureDiv` finds the signature as the first `div[id="AppleMailSignature"]` outside a quote. `_copyHtmlStringFromRange(…)` runs `recursivelyRemoveMailAttributes(!i, …)` on the HTML it copies out of the editor. The native send-time serializer was not traced to its call.
  implication: The id is how the editor finds the signature while it edits. The HTML that Mail copies out of the editor can lose it. This matches the 05.2-16 delivered HTML. Not proven: which flag value the send path passes (only the device result is proof).

- timestamp: 2026-11-14
  checked: `uv run pytest -q tests/test_mail_reply_cleanup.py tests/test_mail_reply_window.py -k "signature or is_own"`
  found: 47 passed, including the `_SIG_WS` case (a signature block with no id, a link and `&nbsp;`: accepted).
  implication: The unit suite already pins that the sweep finds the signature by text, not by id.

- timestamp: 2026-11-14
  checked: throwaway `uv run python -c` (no file written): `_split_quote` + `_is_own` + `_has_quote` on six synthetic Mail-shaped bodies (call text "Hi there", signature "Jane Doe / Example Corp", attribution inside `blockquote type="cite"`)
  found: draft shape with `id="AppleMailSignature"`: own True, quote True. Delivered shape, id stripped: True, True. Delivered with a logo `img` and a link: True, True. No signature in the body although the signature read: True, True. Signature text with an extra `--` line: own False. Signature below the quote: own True, quote False.
  implication: The id has no effect on the verdict. The two body shapes that fail the set-aside rule are text drift (more than white space) and a signature below the quote. Neither is shown by the 05.2-16 record.

- timestamp: 2026-11-14
  checked: reply insert path (`runtime` insert work(), `mail_outgoing` `reply_all` dispatch, `_REPLY_OPEN`)
  found: A quoted reply (`include_quote=True`, the 05.2-16 D call) pastes at the caret with no Cmd-A; Cmd-A runs only when `replace_all` (no quote). `_REPLY_OPEN` only reads `message signature` and its `content`; no script writes `message signature`, `content` or `html content` on a reply.
  implication: No code path of ours removes, rewrites or moves the signature in a quoted reply. Nothing in our code depends on, adds or strips the id. The product defect (a) is not supported.

- timestamp: 2026-11-14
  checked: `find_own_draft` (mail_reply_cleanup.py 352-376) against the 05.2-16 D topology (reply sent from one account to the owner's Gmail address, which the plan exports from Mail)
  found: Every new row whose In-Reply-To is the original and that is neither a Drafts row nor a Sent/`[Gmail]/All Mail` twin is appended as `unproven`. The delivered copy of a self-addressed reply, received in the recipient account's INBOX on the same Mac, is such a row. The parametrized case `imap://…/INBOX` -> `unproven` exists (test_mail_reply_cleanup.py 291); no after-send test has a received INBOX copy.
  implication: Not this gap, but relevant to the sibling session: if the recipient account is in Mail on the test Mac and its INBOX row (or an unreadable `.emlx`, R3) exists at +45 s, the sweep returns `unproven` whatever the signature shape. Unverified: the record does not say whether that account is in Mail or when the copy arrived.

## Resolution

root_cause: "(b) wrong test assumption. The 05.2-16 method (`sig_hash.py --eml`, 05.2-16-PLAN context) finds the delivered signature only as the element with `id=AppleMailSignature`. That id is Mail's compose-time editing handle (the editor finds and replaces the signature by it). Mail's own compose code strips it as a Mail attribute and removes it on the first edit. The delivered HTML therefore had no such element, and the method could not compare. The assumption came from the 05.2-13 sighting in a compose-time copy and was never checked on a delivered message. No product code reads, writes or depends on the id; the quoted-reply path does not touch the signature. Open, not shown by the record: whether the signature TEXT was present in the delivered message."
fix:
verification:
files_changed: []
