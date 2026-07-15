"""Per-app adapters — one module per macOS app.

Each module owns its access method (EventKit / AppleScript / osxphotos) behind the
``contracts.PointerSource`` Protocol (reads) plus its own typed write methods. An
adapter must not reach into another adapter. Adding an app = add a module here +
mount its tools in ``server.py``.
"""
