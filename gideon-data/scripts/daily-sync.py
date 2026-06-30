#!/usr/bin/env python3
"""
Wrapper for the daily sync cron job. Hermes no-agent cron calls this script.
It delegates to the canonical sync script in /opt/plansync/sync/.
"""

import os
import subprocess
import sys

SYNC_SCRIPT = "/opt/plansync/sync/daily_sync.py"

env = os.environ.copy()
env.setdefault("PLANSYNC_DB", "/opt/plansync/plansync.db")
env.setdefault("PLANSYNC_OUTPUT_DIR", "/opt/plansync/sync-output")

result = subprocess.run(
    [sys.executable, SYNC_SCRIPT],
    env=env,
    capture_output=False,
)
sys.exit(result.returncode)
