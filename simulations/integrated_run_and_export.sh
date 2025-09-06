#!/usr/bin/env bash
# Run selected OMNeT++ .ini(s) and export JSON *after each run*, area-aware.

set -euo pipefail

# ----- paths anchored to simulations/ -----
SIM_DIR="$(cd "$(dirname "$0")" && pwd)"
EXAMPLES_DIR="$SIM_DIR/examples"
RESULTS_DIR="$SIM_DIR/results"
FLORA_SRC="$SIM_DIR/../src"
INET_SRC="$SIM_DIR/../../inet4.4/src"
EXPORTER="$SIM_DIR/complete_export_all_scenarios.sh"   # proven exporter

export PATH="$FLORA_SRC:$INET_SRC:$PATH"
NED_PATH=".:..:../../src:../../../inet4.4/src"

# ----- scenario catalog (relative to examples/) -----
SCENARIOS=(
  # s01
  "omnetpp-scenario-01-01_fixed_baseline.ini"
  "omnetpp-scenario-01-02_sf_only.ini"
  "omnetpp-scenario-01-03_tp_only.ini"
  "omnetpp-scenario-01-04_no_init.ini"
  "omnetpp-scenario-01-05_adr_sf_init.ini"
  "omnetpp-scenario-01-06_adr_tp_init.ini"
  "omnetpp-scenario-01-07_adr_both_init.ini"
  "omnetpp-scenario-01-08_adr_no_init.ini"
  # s02
  "omnetpp-scenario-02-adr-enabled.ini"
  "omnetpp-scenario-02-fixed-sf12.ini"
  # s03
  "omnetpp-scenario-03-sf7-fixed.ini"
  "omnetpp-scenario-03-sf8-fixed.ini"
  "omnetpp-scenario-03-sf9-fixed.ini"
  "omnetpp-scenario-03-sf10-fixed.ini"
  "omnetpp-scenario-03-sf11-fixed.ini"
  "omnetpp-scenario-03-sf12-fixed.ini"
  # s04
  "omnetpp-scenario-04-confirmed.ini"
  "omnetpp-scenario-04-unconfirmed.ini"
  # s05
  "omnetpp-scenario-05-low-traffic.ini"
  "omnetpp-scenario-05-medium-traffic.ini"
  "omnetpp-scenario-05-high-traffic.ini"
  # s06
  "omnetpp-scenario-06-sf7-collision.ini"
  "omnetpp-scenario-06-sf10-collision.ini"
  "omnetpp-scenario-06-sf12-collision.ini"
  # s07
  "omnetpp-scenario-07-freespace.ini"
  "omnetpp-scenario-07-logdist-32.ini"
  "omnetpp-scenario-07-logdist-35.ini"
  "omnetpp-scenario-07-logdist-40.ini"
  "omnetpp-scenario-07-logdist-376.ini"
  # s08
  "omnetpp-scenario-08-1gw.ini"
  "omnetpp-scenario-08-2gw.ini"
  "omnetpp-scenario-08-4gw.ini"
)

lower(){ tr '[:upper:]' '[:lower:]'; }

area_dir_of(){
  local a="$(echo "${1:-}" | lower | tr -d ' ')"
  case "$a" in
    1km|1x1km) echo "$EXAMPLES_DIR/updated_ini_1km";;
    2km|2x2km) echo "$EXAMPLES_DIR/updated_ini_2km";;
    3km|3x3km) echo "$EXAMPLES_DIR/updated_ini_3km";;
    4km|4x4km) echo "$EXAMPLES_DIR/updated_ini_4km";;
    5km|5x5km) echo "$EXAMPLES_DIR/updated_ini_5km";;
    "") echo "";;
    *)  echo ""; return 1;;
  esac
}

resolve_scenarios_group(){
  local sel="$(echo "$1" | lower)"
  if [[ "$sel" =~ ^(omnetpp-)?scenario-([0-9]{1,2})$ ]]; then
    local n="${BASH_REMATCH[2]}"
    printf -v n2 "%02d" "$n"
    local prefix="omnetpp-scenario-${n2}-"
    for ini in "${SCENARIOS[@]}"; do
      [[ "$(echo "$ini" | lower)" == ${prefix}* ]] && echo "$ini"
    done
    return 0
  fi
  return 1
}

resolve_one_ini(){
  local sel="$(echo "$1" | lower)"
  # numeric index
  if [[ "$sel" =~ ^[0-9]+$ ]]; then
    local idx="$sel"
    (( idx>=1 && idx<=${#SCENARIOS[@]} )) && { echo "${SCENARIOS[$((idx-1))]}"; return 0; }
  fi
  # exact or fuzzy name
  for ini in "${SCENARIOS[@]}"; do [[ "$(echo "$ini" | lower)" == "$sel" ]] && { echo "$ini"; return 0; }; done
  for ini in "${SCENARIOS[@]}"; do [[ "$(echo "$ini" | lower)" == *"$sel"* ]] && { echo "$ini"; return 0; }; done
  return 1
}

run_ini(){
  local ini_full="$1"
  echo ""
  echo "=== RUN: $(basename "$ini_full") ==="
  ( cd "$EXAMPLES_DIR" && \
    opp_run -u Cmdenv -c General \
      -f "$(realpath --relative-to="$EXAMPLES_DIR" "$ini_full")" \
      -n "$NED_PATH" -l "$FLORA_SRC/flora" -l "$INET_SRC/INET" )
  echo "=== DONE: $(basename "$ini_full") ==="
}

export_for_ini(){
  local ini_full="$1"
  [[ -x "$EXPORTER" ]] || { echo "❌ exporter missing: $EXPORTER"; exit 2; }
  echo ">>> Exporting JSON for $(basename "$ini_full")"
  "$EXPORTER" "$ini_full"     # <— passes *only this INI* to exporter
}

# ----- CLI -----
SCEN_SEL=""
AREA=""
DO_EXPORT=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    -s|--scenario) SCEN_SEL="${2:-}"; shift 2;;
    --area)        AREA="${2:-}"; shift 2;;
    --no-export)   DO_EXPORT=0; shift;;
    -h|--help)
      echo "Usage:"
      echo "  $0 -s <scenario|index|scenario-XX> [--area 1x1km|2x2km|...]"
      echo "  $0 --area 1x1km         # run all INIs in that area folder"
      echo "  $0                      # run ALL INIs in base examples/ (not area-specific)"
      exit 0;;
    *) echo "Unknown arg: $1"; exit 2;;
  esac
done

AREA_DIR="$(area_dir_of "$AREA" || true)"
if [[ -n "$AREA" && -z "${AREA_DIR:-}" ]]; then
  echo "❌ bad --area '$AREA' (use 1x1km..5x5km or 1km..5km)"; exit 2
fi

echo "SIM_DIR     : $SIM_DIR"
echo "EXAMPLES    : $EXAMPLES_DIR"
echo "AREA_DIR    : ${AREA_DIR:-<none>}"
echo "RESULTS_DIR : $RESULTS_DIR"
echo "Export      : $([[ $DO_EXPORT -eq 1 ]] && echo yes || echo no)"
echo ""

# ----- selection matrix -----

run_and_export(){
  local ini_rel="$1"
  local base_dir="${AREA_DIR:-$EXAMPLES_DIR}"
  local ini_full="$base_dir/$ini_rel"
  if [[ ! -f "$ini_full" ]]; then
    echo "⚠️  skip (missing): $ini_full"; return
  fi
  run_ini "$ini_full"
  [[ $DO_EXPORT -eq 1 ]] && export_for_ini "$ini_full"
}

if [[ -n "$SCEN_SEL" ]]; then
  # Try group first, but only if it returns NON-EMPTY output
  GROUP_OUTPUT="$(resolve_scenarios_group "$SCEN_SEL" || true)"
  if [[ -n "$GROUP_OUTPUT" ]]; then
    # we have a real group
    mapfile -t GROUP <<< "$GROUP_OUTPUT"
    echo "Group '${SCEN_SEL}' → ${#GROUP[@]} INIs"
    for ini in "${GROUP[@]}"; do
      run_and_export "$ini"
    done
    exit 0
  fi

  # Not a group → resolve single ini (index / exact / fuzzy)
  ONE="$(resolve_one_ini "$SCEN_SEL")" || { echo "❌ unknown scenario: $SCEN_SEL"; exit 2; }
  run_and_export "$ONE"
  exit 0
fi


# only area given → run every ini in that area folder
if [[ -n "${AREA_DIR:-}" ]]; then
  echo "Running all INIs in area dir: $AREA_DIR"
  shopt -s nullglob
  for ini_full in "$AREA_DIR"/*.ini; do
    run_ini "$ini_full"
    [[ $DO_EXPORT -eq 1 ]] && export_for_ini "$ini_full"
  done
  exit 0
fi

# default: run ALL catalog INIs from base examples/
echo "Running all catalog INIs from examples/"
for ini in "${SCENARIOS[@]}"; do run_and_export "$ini"; done
