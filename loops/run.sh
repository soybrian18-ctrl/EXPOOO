#!/bin/bash
# run.sh -- venv-activation wrapper for the loop scripts (invoked by launchd).
#
# launchd runs jobs with a minimal environment and no activated virtualenv, so
# this wrapper pins the working directory to the project root, activates the
# project's .venv, and execs the requested loop script under that interpreter.
#
# Usage:  loops/run.sh loops/token_refresh_monitor.py [args...]
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if [ ! -f ".venv/bin/activate" ]; then
  echo "ERROR: virtualenv not found at $PROJECT_ROOT/.venv" >&2
  exit 1
fi

# shellcheck disable=SC1091
source ".venv/bin/activate"

exec python "$@"
