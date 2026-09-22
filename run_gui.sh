#!/bin/bash
# WebAgent GUI Launcher

cd "$(dirname "$0")"
./venv/bin/python scripts/macos_gui.py "$@"
