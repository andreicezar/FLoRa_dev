#!/usr/bin/env bash
set -euo pipefail

SIM_DIR="$(cd "$(dirname "$0")" && pwd)"     # .../flora/simulations
EXAMPLES="$SIM_DIR/examples"

# Do NOT source setenv (as requested)
# Ensure DLLs are discoverable (safe to keep)
export PATH="$SIM_DIR/../src:$SIM_DIR/../../inet4.4/src:$PATH"

cd "$EXAMPLES"

# If you provide NED_DIR_OVERRIDE (a directory), use it INSTEAD of '..'
if [ -n "${NED_DIR_OVERRIDE:-}" ] && [ -d "$NED_DIR_OVERRIDE" ]; then
  NED_PATH=".:$NED_DIR_OVERRIDE:../../src:../../../inet4.4/src"
  echo "Using NED_DIR_OVERRIDE: $NED_DIR_OVERRIDE"
else
  NED_PATH=".:..:../../src:../../../inet4.4/src"
fi

SCENARIO="${1:-omnetpp-scenario-01-01_fixed_baseline.ini}"
echo "NED_PATH=$NED_PATH"
echo "SCENARIO=$SCENARIO"

opp_run -u Cmdenv -c General -f "$SCENARIO" \
  -n "$NED_PATH" \
  -l ../../src/flora \
  -l ../../../inet4.4/src/INET
