#!/bin/bash
# Morning briefing — dispatch HTTP API, delivered verbatim to Telegram.
set -euo pipefail
exec curl -sf http://dispatch:8082/api/briefing
