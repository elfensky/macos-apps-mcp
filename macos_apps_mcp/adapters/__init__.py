"""Per-app adapters — one module per macOS app.

Each module owns its access method (EventKit / AppleScript / osxphotos). Query-shaped
searches implement the ``contracts.PointerSource`` Protocol; enumeration reads
(``safari_tabs``, ``messages_chats``) are per-adapter typed methods, like the writes.
An adapter must not reach into another adapter. Adding an app = add a module here +
mount its tools in ``server.py``.
"""
