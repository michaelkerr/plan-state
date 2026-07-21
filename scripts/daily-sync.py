#!/usr/bin/env python3
"""
Wrapper for the daily sync cron job. Hermes no-agent cron calls this script.
It delegates to the canonical sync script in /opt/plansync/sync/.
"""

import os
import subprocess
import sys

SYNC_SCRIPT = "/opt/plansync/sync/daily_sync.py"
DOSSIER_SCRIPT = "/opt/plansync/sync/export_dossier.py"

env = os.environ.copy()
env.setdefault("PLANSYNC_DB", "/opt/data/plansync/plansync.db")
env.setdefault("PLANSYNC_OUTPUT_DIR", "/opt/plansync/sync-output")

result = subprocess.run(
    [sys.executable, SYNC_SCRIPT],
    env=env,
    capture_output=False,
)

# Refresh per-domain dossiers after the sync. Writes files only (stdout here
# is delivered to Telegram, so the exporter reports on stderr); a dossier
# failure must not fail the sync heartbeat.
subprocess.run([sys.executable, DOSSIER_SCRIPT], env=env, capture_output=False, stdout=sys.stderr)

sys.exit(result.returncode)
