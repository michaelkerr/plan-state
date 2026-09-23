#!/bin/bash
# Hourly dispatch eval — weather pull and trigger evaluation.
# Stdout is delivered locally. Empty or JSON; not a Telegram message.
set -euo pipefail
exec curl -sf http://plansync-new:8082/api/eval
