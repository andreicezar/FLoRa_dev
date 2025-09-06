#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# Run all FLoRa analyzers (01..08) for all areas (1x1km..5x5km).
# Usage:
#   ./run_all_flora_analyzers.sh
#
# Options (env vars):
#   AREAS   - space-separated list of areas (default: "1x1km 2x2km 3x3km 4x4km 5x5km")
#             accepts also compact "1km .. 5km" as your analyzers normalize aliases.
#   PYTHON  - python interpreter (default: python3)
#   JSON_DIR- override json_exports location (passed via --json-dir if set)
# -----------------------------------------------------------------------------

PYTHON="${PYTHON:-python3}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Default areas if not provided
if [[ -z "${AREAS:-}" ]]; then
  AREAS="1x1km 2x2km 3x3km 4x4km 5x5km"
fi

# Collect available Flora analyzers (only those that exist)
declare -a ANALYZERS=()
for n in 01 02 03 04 05 06 07 08; do
  f="analyze_flora_scenario_${n}.py"
  [[ -f "$SCRIPT_DIR/$f" ]] && ANALYZERS+=("$f")
done

if [[ ${#ANALYZERS[@]} -eq 0 ]]; then
  echo "No analyze_flora_scenario_*.py files found in $SCRIPT_DIR" >&2
  exit 2
fi

bold() { printf "\033[1m%s\033[0m\n" "$*"; }
info() { printf "  \033[36m%s\033[0m\n" "$*"; }
warn() { printf "  \033[33m%s\033[0m\n" "$*"; }
err () { printf "  \033[31m%s\033[0m\n" "$*" >&2; }

bold "🌿 Running FLoRa analyzers for all areas"
info "Using Python: $PYTHON"
info "Analyzer dir: $SCRIPT_DIR"
info "Areas       : $AREAS"
[[ -n "${JSON_DIR:-}" ]] && info "json dir    : $JSON_DIR"
echo

overall_fail=0
declare -a failed

for area in $AREAS; do
  bold "📍 Area: $area"
  for script in "${ANALYZERS[@]}"; do
    path="$SCRIPT_DIR/$script"
    args=( "$path" "--area" "$area" )
    [[ -n "${JSON_DIR:-}" ]] && args+=( "--json-dir" "$JSON_DIR" )

    info "▶ ${script} --area ${area}"
    set +e
    "$PYTHON" "${args[@]}"
    code=$?
    set -e

    if [[ $code -ne 0 ]]; then
      warn "✖ ${script} (area ${area}) exited with code ${code}"
      overall_fail=1
      failed+=("${script} --area ${area} [exit=${code}]")
    else
      info "✔ ${script} (area ${area}) completed"
    fi
    echo
  done
done

if [[ $overall_fail -ne 0 ]]; then
  bold "⚠️  Some analyzers reported errors:"
  for f in "${failed[@]}"; do err " - $f"; done
  exit 1
fi

bold "🎉 All FLoRa analyzers ran successfully for all areas."
