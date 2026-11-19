# Installed acceptance working notes — 2026-11-04

- Two research handoffs stopped before supplying a runnable harness. The parent prepared bounded stdio, dashboard, restart, and census harnesses.
- The native test census collected 105 cases across ten files. The broad suite was not run: fixtures include default/shared containers, persistent scratch data, sends, playback changes, and indexing writes.
- `test_doctor_integration_real` failed with `AssertionError: assert 12 == 11`. Its count omitted the Accessibility surface. The assertion and explanatory comment now include that existing surface. Runtime code is unchanged.
- The corrected read-only subset returned `3 passed, 1 skipped, 193 deselected`. The skipped test requires a running Mail process.
- Sandboxed codesign reported `invalid signature (code or signature have been modified)`. Strict verification outside the sandbox passed for both the installed app and preserved signed artifact. Do not treat restricted verification as proof of modified bytes.
- At the first installation check, the signed archive had no ticket. Later notarization and Intel installation passed; no Gatekeeper bypass was used.
- The installed restart test used the documented launchctl kickstart. It waited for a new socket inode and listener before one explicit list and doctor call. It does not establish behavior during a controlled absence or measure automatic replay.
- The signed installed build remains 7bc8607. This branch changes an integration assertion and evidence only; it does not imply a rebuilt runtime from the evidence commit.

- Final branch gates: 3475 passed, 105 deselected, seven upstream warnings; Ruff lint/format passed; 98 relative links resolved.

- The owner authorized one self-addressed message. The installed send, Trash, and undo completed; the Trash call took 6.087 seconds. No uncertain response was replayed.
- The initial provider heuristic saw no Google namespace. A later account probe found a custom IMAP host; provider classification remains unknown, not proven non-Gmail.
- Delayed observations began after undo. They prove the restored state persisted, not that Trash persisted for two or fifteen minutes. Keep the Gmail Trash gate open.
- The root checked every new backup directory component through the state directory and reverified the installed signature outside the sandbox after Mail activity.

- The initial notarization search checked the account email as a profile name and missed the existing `notary` profile. Earlier release records already named it.
- After the owner accepted Apple's agreement, `notarytool history --keychain-profile notary` returned success with 16 submissions. No credential was exported or replaced.
- The unnecessary private password request was terminated. Read the recorded profile before requesting a new secret; authentication success is separate from the new bundle's acceptance.

- The notarization upload succeeded before its shell wrapper failed on zsh's reserved `status` variable. The worker recovered the submission ID and queried it; it did not upload twice.
- Intel signature checks and SSH failed inside the sandbox but passed with the authorized access. The worker preserved a rollback bundle and verified the installed daemon and signature after bounded reads.
