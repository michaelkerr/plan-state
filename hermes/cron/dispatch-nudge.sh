#!/bin/bash
# Evening nudge — dispatch HTTP API. Empty body stays silent.
set -euo pipefail
exec curl -sf http://dispatch:8082/api/nudge
