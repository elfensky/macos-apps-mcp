# The .app only (scripts/build_app.sh copies it into the bundle's site-packages); never
# the wheel, where it would take over every environment that installs the package.
# Finder, the Dock and Spotlight start the bundle with no arguments: run the `launch`
# role. Every other caller (launchd, the shim, the CLI wrapper, the build) passes
# arguments. Python runs this file on EVERY start and an exception here fails the
# process silently, so the daemon's path is one length check and nothing else.
import sys

if len(sys.orig_argv) == 1:
    import os

    exe = sys.executable
    os.execv(exe, [exe, "-E", "-s", "-P", "-m", "macos_apps_mcp", "launch"])
