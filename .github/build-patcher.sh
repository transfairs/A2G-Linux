#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Builds src/a2patcher.exe from src/a2patcher.py with PyInstaller: one file with Python, the scripts
# it runs and the prebuilt code of src/a2manager.json and src/a2v101.json. Needs a Windows Python
# (the release and tests workflows run it on windows-latest, in Git Bash). Checks the result with
# --help. Relative paths only, so that Git Bash hands them to the Windows Python unchanged.
#
#   .github/build-patcher.sh [output]    (default: src/a2patcher.exe)
set -euo pipefail
cd "$(dirname "$0")/.."
out="${1:-src/a2patcher.exe}"
work=.a2patcher-build
rm -rf "$work"
trap 'rm -rf "$work" a2patcher.spec' EXIT
python -m pip install --quiet pyinstaller==6.11.1
python -m PyInstaller --onefile --console --noconfirm --log-level WARN --name a2patcher \
  --distpath "$work/dist" --workpath "$work/build" --paths src \
  --add-data "src/a2manager.json;." --add-data "src/a2v101.json;." src/a2patcher.py
"$work/dist/a2patcher.exe" --help >/dev/null
cp "$work/dist/a2patcher.exe" "$out"
echo "$out built ($(du -h "$out" | cut -f1))"
