#!/bin/bash
# Wrapper that calls the Python briefing-context script.
set -euo pipefail
exec python3 /opt/data/scripts/briefing-context.py
