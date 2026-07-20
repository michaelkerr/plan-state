#!/usr/bin/env python3
"""
Wrapper for the evening nudge cron job. Hermes no-agent cron calls this script.
It delegates to the canonical script in /opt/plansync/sync/.
"""

import os
import subprocess
import sys

NUDGE_SCRIPT = "/opt/plansync/sync/evening_nudge.py"

env = os.environ.copy()
env.setdefault("PLANSYNC_DB", "/opt/plansync/plansync.db")

result = subprocess.run(
    [sys.executable, NUDGE_SCRIPT],
    env=env,
    capture_output=False,
)
sys.exit(result.returncode)
