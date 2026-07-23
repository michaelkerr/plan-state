#!/usr/bin/env python3
"""
Wrapper for the evening nudge cron job. Hermes no-agent cron calls this script.
It delegates to the canonical script in /opt/plansync/sync/.

Runs a lightweight sync (dossier + domain JSON export) before the nudge so
any changes made during the day are captured in the on-disk files before
the evening reminder goes out.
"""

import os
import subprocess
import sys

NUDGE_SCRIPT = "/opt/plansync/sync/evening_nudge.py"
DOSSIER_SCRIPT = "/opt/plansync/sync/export_dossier.py"
DOMAIN_JSON_SCRIPT = "/opt/plansync/sync/export_domain_json.py"

env = os.environ.copy()
env.setdefault("PLANSYNC_DB", "/opt/data/plansync/plansync.db")

# Refresh dossiers and domain JSON before the nudge. Failures here should not
# block the nudge itself, so we swallow exit codes and route output to stderr.
subprocess.run([sys.executable, DOSSIER_SCRIPT], env=env, capture_output=False, stdout=sys.stderr)
subprocess.run([sys.executable, DOMAIN_JSON_SCRIPT], env=env, capture_output=False, stdout=sys.stderr)

result = subprocess.run(
    [sys.executable, NUDGE_SCRIPT],
    env=env,
    capture_output=False,
)
sys.exit(result.returncode)
