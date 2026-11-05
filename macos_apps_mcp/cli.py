"""Role dispatch (#71). Bare invocation stays the stdio server byte-for-byte — every
existing client config keeps working. Roles are positional argv (no flags): the bundle
executable and the venv entry point share this dispatch."""

from __future__ import annotations

import sys

_ROLES = (
    "daemon",
    "shim",
    "register",
    "unregister",
    "install-agent",
    "uninstall-agent",
    "allow-send",
    "dashboard",
    "launch",
    "dedupe-mail",
    "index-mail-ids",
)


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] in _ROLES:  # named roles require macOS, before storage access
        from . import runtime
        from .errors import UnsupportedPlatform

        try:
            runtime.require_macos()
        except UnsupportedPlatform as e:
            print(e, file=sys.stderr)
            raise SystemExit(1) from None
    if not args or args[0] in ("daemon", "dedupe-mail", "index-mail-ids"):
        from .audit import state_dir
        from .text import sanitize_line

        try:
            state_dir()  # #540: attempt repair before serving; each writer rechecks
        except OSError as e:
            # Keep tools/list and doctor available. Private storage still refuses
            # unsafe paths; audit persistence retains its existing best-effort policy.
            reason = sanitize_line(str(e))[:400]
            print(f"cannot protect state storage: {reason}", file=sys.stderr)
    if not args:
        from . import server

        server.main()  # stdio — bootstrap + lifecycle guards, unchanged
        return
    role = args[0]
    if role == "daemon":
        from . import daemon

        daemon.serve()  # no lifecycle guards: launchd KeepAlive owns restart
    elif role == "shim":
        from . import daemon

        daemon.run_shim()
    elif role in ("register", "unregister"):
        from . import deploy

        (deploy.register_agent if role == "register" else deploy.unregister_agent)()
    elif role == "install-agent":
        from . import deploy

        deploy.install_agent(args[1:])
    elif role == "uninstall-agent":
        from . import deploy

        deploy.uninstall_agent()
    elif role == "allow-send":
        from . import deploy

        deploy.allow_send(args[1:])
    elif role == "dashboard":
        from . import deploy

        deploy.dashboard(args[1:])
    elif role == "launch":  # opening the .app: the bundle's sitecustomize starts it
        from . import deploy

        deploy.launch(args[1:])
    elif role == "dedupe-mail":
        # CLI-only by design (#140): thousands of ~0.1s deletes against a 30s-capped
        # serialized worker is a job a human starts, not a tool call. The MCP surface
        # gets the read-only `mail_duplicates()` report instead.
        from . import dedupe

        dedupe.dedupe_mail(args[1:])
    elif role == "index-mail-ids":
        # The initial Message-ID sidecar build (#201) — the mail_index_ids tool's
        # CLI twin, following the dedupe-mail precedent: a potentially minutes-long
        # first build is a job a human starts.
        from .adapters import mail_ids, mail_index

        stats = mail_ids.build(mail_index.require_index_path())
        for k, v in stats.items():
            print(f"{k}: {v}")
    else:
        print(f"unknown role {role!r}; one of: {', '.join(_ROLES)}", file=sys.stderr)
        raise SystemExit(2)
