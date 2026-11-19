# Notarization and physical Intel acceptance — 2026-11-04

Apple accepted the universal app built from `7bc86078e64bfbbe8d019cda8ef85a0dcc11583f`.
The stapled app is installed on the physical Intel Mac. Its installed shim reaches the new daemon.
The previous Intel app remains available as a separate rollback bundle.

## Verified outcome

| Check | Result |
|---|---|
| Authentication | Existing Keychain profile `notary`; no new credential or secret export |
| Apple submission | `4e2b31e0-74db-4fc7-ab48-aa80c115752d`, status `Accepted` |
| Staple and archive | Ticket attached and validated; distribution archive created after stapling |
| Artifact verification | Strict signature and local Gatekeeper assessment passed |
| Physical target | x86_64 Mac, macOS 15.8.1 |
| Installed identity | Version `0.15.1`, build `7bc8607 2026-11-04T11:41:03Z`, daemon mode |
| Runtime libraries | MCP `2.3.0`, FastMCP `4.1.6` |
| Protocol compatibility | Legacy and modern installed clients each listed 68 annotated tools; `ping` and `now` passed |
| Native reads | Calendar enumeration, reminder-list enumeration, and one-day free/busy passed |
| Native result notices | Exactly one notice, first, with structured content preserved |
| Final installed seal | Strict signature, staple validation, and Intel Gatekeeper assessment passed after testing |

The parent independently queried the exact submission and confirmed `Accepted`.
The parent also verified the stapled archive's SHA-256 against the worker's record.

| Artifact | SHA-256 |
|---|---|
| Submission archive | `f150d42318792c16f998e35e3cdb43293c7fb0ecfa6cb48c618486f192e51ee2` |
| Stapled distribution archive | `fea110c0740fa7ba968fe4c13711b8cda86ee9102b9482406f3da1ee7ab59594` |
| Installed executable | `dbca46d70f487bd6075b7029e36b60b28c98a1d96b411beb9621140977315737` |

## Scope and remaining acceptance

This task did not replace or restart the local arm64 installation. Its [earlier installed checks](2026-11-04-installed-acceptance.md) remain separate evidence.
The local Gatekeeper result concerns the stapled build artifact, not a new check of the arm64 installed app.
The [Mail recovery fixture](2026-11-04-mail-recovery-acceptance.md) ran only on arm64.

No real Claude frontend, controlled outage, replay-count experiment, localized Mail write, or Gmail Trash persistence test was performed.
PR #559 was not installed; its ambiguity, dedupe and undo guards remain untested on these installations.
The Intel task performed no native write. No release tag, public release, or package upload was made.
The migration remains open for its remaining native/frontend and release criteria.

**eli14:** Apple's inspection stamp is attached to the toolbox. The older Mac now runs the same new tools.
Its basic read tools passed. Specialized Mail routes and release delivery still need their own checks.

## Evidence

The private installation directory retains the submission result, acceptance data, hashes, report, working notes, and stapled archive.
Machine-specific locations and rollback paths remain outside this public repository.
The [profile runbook](../../docs/DAEMON.md#notarization-profile) records the credential alias and recovery checks.
The [working notes](2026-11-04-installed-working-notes.md) preserve the resolved authentication and command-wrapper failures.
