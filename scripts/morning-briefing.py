#!/usr/bin/env python3
"""
Wrapper for the deterministic morning briefing. Hermes cron calls this
(via morning-briefing.sh). It delegates to the canonical script in
/opt/plansync/sync/ so the logic stays live-editable on the volume mount.
"""

import os
import subprocess
import sys

BRIEFING_SCRIPT = "/opt/plansync/sync/morning_briefing.py"

env = os.environ.copy()
env.setdefault("PLANSYNC_DB", "/opt/data/plansync/plansync.db")

result = subprocess.run([sys.executable, BRIEFING_SCRIPT], env=env, capture_output=False)
sys.exit(result.returncode)
