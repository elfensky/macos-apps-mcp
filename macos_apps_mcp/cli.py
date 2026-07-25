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
)


def main() -> None:
    args = sys.argv[1:]
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
    else:
        print(f"unknown role {role!r}; one of: {', '.join(_ROLES)}", file=sys.stderr)
        raise SystemExit(2)
