"""macos-apps-mcp — one consolidated MCP server for native macOS apps."""

from .cli import main
from .server import mcp

__all__ = ["main", "mcp"]
