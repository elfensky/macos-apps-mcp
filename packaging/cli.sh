#!/bin/bash
# The CLI on PATH (Contents/Resources/bin/macos-apps-mcp, linked into ~/.local/bin by
# `launch` and `install-agent`): the bundled interpreter with its isolation flags
# (docs/DAEMON.md section 4). realpath follows the link back into the bundle.
set -euo pipefail
exec "$(dirname "$(/bin/realpath "$0")")/../../MacOS/macos-apps-mcp" \
  -E -s -P -m macos_apps_mcp "$@"
