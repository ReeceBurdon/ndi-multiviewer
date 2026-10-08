#!/bin/bash
# Builds "NDI Multiviewer.app" on this Mac and opens the folder it lands in.
# Run from Terminal:  bash build_mac.command   (or double-click it in Finder)
set -e
cd "$(dirname "$0")"

# cyndilib (the NDI library) needs Python 3.10 or newer.
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.10 or newer is needed to build the app (not to run it)."
  echo "Install it with:  brew install python    or from https://www.python.org/downloads/macos/"
  exit 1
fi
echo "Using $("$PY" --version) at $(command -v "$PY")"

"$PY" -m venv .build-venv
. .build-venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt pyinstaller
pyinstaller --noconfirm --log-level WARN packaging/ndi_multiviewer.spec

echo
echo "Built: $(pwd)/dist/NDI Multiviewer.app"
echo "Drag it to Applications if you like. Click Allow when macOS asks about your local network."
open dist
