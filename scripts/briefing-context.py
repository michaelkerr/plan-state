#!/usr/bin/env python3
"""
Wrapper for the morning briefing context. Hermes cron calls this (via
briefing-context.sh). It delegates to the canonical script in
/opt/plansync/sync/ so the logic stays live-editable on the volume mount.
"""

import os
import subprocess
import sys

BRIEFING_SCRIPT = "/opt/plansync/sync/briefing_context.py"

env = os.environ.copy()
env.setdefault("PLANSYNC_DB", "/opt/data/plansync/plansync.db")
env.setdefault("PLANSYNC_OUTPUT_DIR", "/opt/data/plansync/sync-output")

result = subprocess.run([sys.executable, BRIEFING_SCRIPT], env=env, capture_output=False)
sys.exit(result.returncode)
