#!/bin/bash
# WebAgent GUI Launcher

cd "$(dirname "$0")"
./venv/bin/python webagent_gui.py "$@"
