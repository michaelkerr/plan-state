#!/bin/bash
# Wrapper that calls the Python morning briefing script.
set -euo pipefail
exec python3 /opt/data/scripts/morning-briefing.py
