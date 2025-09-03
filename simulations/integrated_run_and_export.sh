#!/usr/bin/env bash
# FLoRa: run scenarios + export JSON (no empty files; print counts & sizes)
# - Two functions: run_scenario, export_scenario
# - Default: run each scenario, then export {scalars, parameters, histograms, app vectors}
# - --export=false / --no-export: skip exports
# - --scenario <N|name|ini|scenario-XX>: run/export a single INI or ALL sub-scenarios of scenario-XX

set -euo pipefail

# ---------- Paths
SIM_DIR="$(cd "$(dirname "$0")" && pwd)"           # .../flora/simulations
EXAMPLES_DIR="$SIM_DIR/examples"
RESULTS_DIR="$SIM_DIR/results"
OUTPUT_DIR="$SIM_DIR/json_exports"
FLORA_SRC="$SIM_DIR/../src"
INET_SRC="$SIM_DIR/../../inet4.4/src"

mkdir -p "$OUTPUT_DIR"
export PATH="$FLORA_SRC:$INET_SRC:$PATH"    # DLL resolution on Windows

# ---------- Constants
NED_PATH=".:..:../../src:../../../inet4.4/src"     # purely relative; no overlays

# -----------------------
# Scenario INI inventory
# -----------------------

# NEW: scenarios that should run FIRST (do not affect numeric indices of the main list)
EXTRA_SCENARIOS_FIRST=(
  "n1000-gw1-ADR.ini"
)

# Main set (kept identical; indices 1..32 remain stable)
SCENARIOS=(
  # --- Scenario 01 (8 variants) ---
  "omnetpp-scenario-01-01_fixed_baseline.ini"   # 1
  "omnetpp-scenario-01-02_sf_only.ini"          # 2
  "omnetpp-scenario-01-03_tp_only.ini"          # 3
  "omnetpp-scenario-01-04_no_init.ini"          # 4
  "omnetpp-scenario-01-05_adr_sf_init.ini"      # 5
  "omnetpp-scenario-01-06_adr_tp_init.ini"      # 6
  "omnetpp-scenario-01-07_adr_both_init.ini"    # 7
  "omnetpp-scenario-01-08_adr_no_init.ini"      # 8

  # --- Scenario 02 (2 variants) ---
  "omnetpp-scenario-02-adr-enabled.ini"         # 9
  "omnetpp-scenario-02-fixed-sf12.ini"          # 10

  # --- Scenario 03 (6 variants) ---
  "omnetpp-scenario-03-sf7-fixed.ini"           # 11
  "omnetpp-scenario-03-sf8-fixed.ini"           # 12
  "omnetpp-scenario-03-sf9-fixed.ini"           # 13
  "omnetpp-scenario-03-sf10-fixed.ini"          # 14
  "omnetpp-scenario-03-sf11-fixed.ini"          # 15
  "omnetpp-scenario-03-sf12-fixed.ini"          # 16

  # --- Scenario 04 (2 variants) ---
  "omnetpp-scenario-04-confirmed.ini"           # 17
  "omnetpp-scenario-04-unconfirmed.ini"         # 18

  # --- Scenario 05 (3 variants) ---
  "omnetpp-scenario-05-low-traffic.ini"         # 19
  "omnetpp-scenario-05-medium-traffic.ini"      # 20
  "omnetpp-scenario-05-high-traffic.ini"        # 21

  # --- Scenario 06 (3 variants) ---
  "omnetpp-scenario-06-sf7-collision.ini"       # 22
  "omnetpp-scenario-06-sf10-collision.ini"      # 23
  "omnetpp-scenario-06-sf12-collision.ini"      # 24

  # --- Scenario 07 (5 variants) ---
  "omnetpp-scenario-07-freespace.ini"           # 25
  "omnetpp-scenario-07-logdist-32.ini"          # 26
  "omnetpp-scenario-07-logdist-35.ini"          # 27
  "omnetpp-scenario-07-logdist-376.ini"         # 28
  "omnetpp-scenario-07-logdist-40.ini"          # 29

  # --- Scenario 08 (3 variants) ---
  "omnetpp-scenario-08-1gw.ini"                 # 30
  "omnetpp-scenario-08-2gw.ini"                 # 31
  "omnetpp-scenario-08-4gw.ini"                 # 32
)

# Map INI -> expected results base (no extension), matching your result naming
declare -A RESULT_PREFIX=(
  # EXTRA (runs first)
  ["n1000-gw1-ADR.ini"]="n1000-gw1-ADR"

  # Scenario 01
  ["omnetpp-scenario-01-01_fixed_baseline.ini"]="scenario-01-baseline-01_fixed_baseline"
  ["omnetpp-scenario-01-02_sf_only.ini"]="scenario-01-baseline-02_sf_only"
  ["omnetpp-scenario-01-03_tp_only.ini"]="scenario-01-baseline-03_tp_only"
  ["omnetpp-scenario-01-04_no_init.ini"]="scenario-01-baseline-04_no_init"
  ["omnetpp-scenario-01-05_adr_sf_init.ini"]="scenario-01-baseline-05_adr_sf_init"
  ["omnetpp-scenario-01-06_adr_tp_init.ini"]="scenario-01-baseline-06_adr_tp_init"
  ["omnetpp-scenario-01-07_adr_both_init.ini"]="scenario-01-baseline-07_adr_both_init"
  ["omnetpp-scenario-01-08_adr_no_init.ini"]="scenario-01-baseline-08_adr_no_init"

  # Scenario 02
  ["omnetpp-scenario-02-adr-enabled.ini"]="scenario-02-baseline-adr-enabled"
  ["omnetpp-scenario-02-fixed-sf12.ini"]="scenario-02-baseline-fixed-sf12"

  # Scenario 03
  ["omnetpp-scenario-03-sf7-fixed.ini"]="scenario-03-baseline-sf7-fixed"
  ["omnetpp-scenario-03-sf8-fixed.ini"]="scenario-03-baseline-sf8-fixed"
  ["omnetpp-scenario-03-sf9-fixed.ini"]="scenario-03-baseline-sf9-fixed"
  ["omnetpp-scenario-03-sf10-fixed.ini"]="scenario-03-baseline-sf10-fixed"
  ["omnetpp-scenario-03-sf11-fixed.ini"]="scenario-03-baseline-sf11-fixed"
  ["omnetpp-scenario-03-sf12-fixed.ini"]="scenario-03-baseline-sf12-fixed"

  # Scenario 04
  ["omnetpp-scenario-04-confirmed.ini"]="scenario-04-baseline-confirmed"
  ["omnetpp-scenario-04-unconfirmed.ini"]="scenario-04-baseline-unconfirmed"

  # Scenario 05
  ["omnetpp-scenario-05-low-traffic.ini"]="scenario-05-baseline-low-traffic"
  ["omnetpp-scenario-05-medium-traffic.ini"]="scenario-05-baseline-medium-traffic"
  ["omnetpp-scenario-05-high-traffic.ini"]="scenario-05-baseline-high-traffic"

  # Scenario 06
  ["omnetpp-scenario-06-sf7-collision.ini"]="scenario-06-baseline-sf7-collision"
  ["omnetpp-scenario-06-sf10-collision.ini"]="scenario-06-baseline-sf10-collision"
  ["omnetpp-scenario-06-sf12-collision.ini"]="scenario-06-baseline-sf12-collision"

  # Scenario 07
  ["omnetpp-scenario-07-freespace.ini"]="scenario-07-baseline-freespace"
  ["omnetpp-scenario-07-logdist-32.ini"]="scenario-07-baseline-logdist-32"
  ["omnetpp-scenario-07-logdist-35.ini"]="scenario-07-baseline-logdist-35"
  ["omnetpp-scenario-07-logdist-376.ini"]="scenario-07-baseline-logdist-376"
  ["omnetpp-scenario-07-logdist-40.ini"]="scenario-07-baseline-logdist-40"

  # Scenario 08
  ["omnetpp-scenario-08-1gw.ini"]="scenario-08-baseline-1gw"
  ["omnetpp-scenario-08-2gw.ini"]="scenario-08-baseline-2gw"
  ["omnetpp-scenario-08-4gw.ini"]="scenario-08-baseline-4gw"
)

# Optional fuzzy names to help --scenario matching (kept minimal; names only)
declare -A NAME_HINT=(
  # EXTRA
  [X1]="n1000-gw1-ADR"

  [1]="01_fixed_baseline"
  [2]="02_sf_only"
  [3]="03_tp_only"
  [4]="04_no_init"
  [5]="05_adr_sf_init"
  [6]="06_adr_tp_init"
  [7]="07_adr_both_init"
  [8]="08_adr_no_init"

  [9]="adr-enabled"
  [10]="fixed-sf12"

  [11]="sf7-fixed"
  [12]="sf8-fixed"
  [13]="sf9-fixed"
  [14]="sf10-fixed"
  [15]="sf11-fixed"
  [16]="sf12-fixed"

  [17]="confirmed"
  [18]="unconfirmed"

  [19]="low-traffic"
  [20]="medium-traffic"
  [21]="high-traffic"

  [22]="sf7-collision"
  [23]="sf10-collision"
  [24]="sf12-collision"

  [25]="freespace"
  [26]="logdist-32"
  [27]="logdist-35"
  [28]="logdist-376"
  [29]="logdist-40"

  [30]="1gw"
  [31]="2gw"
  [32]="4gw"
)

# ---------- Args
DO_EXPORT=true
SCENARIO_ARG=""
parse_bool(){ case "$(echo "${1:-}"|tr '[:upper:]' '[:lower:]')" in 0|false|no)echo false;; 1|true|yes)echo true;; *)echo false;; esac; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-export) DO_EXPORT=false; shift ;;
    --export=*)  DO_EXPORT="$(parse_bool "${1#*=}")"; shift ;;
    --scenario|-s) SCENARIO_ARG="${2:-}"; shift 2 ;;
    *) if [[ -z "$SCENARIO_ARG" ]]; then SCENARIO_ARG="$1"; shift; else echo "Unknown arg: $1"; exit 2; fi ;;
  esac
done

# ---------- Helpers
lower(){ echo "$*" | tr '[:upper:]' '[:lower:]'; }

# Return all INIs belonging to a whole scenario group (scenario-XX)
resolve_scenarios_group(){
  local sel="$(lower "$1")"
  local num=""

  # Accept: "scenario-01", "scenario-1", "omnetpp-scenario-01"
  if [[ "$sel" =~ ^(omnetpp-)?scenario-([0-9]{1,2})$ ]]; then
    num="${BASH_REMATCH[2]}"
  else
    return 1
  fi

  printf -v num2 "%02d" "$num"
  local prefix="omnetpp-scenario-${num2}-"
  local out=()
  for ini in "${SCENARIOS[@]}"; do
    local lname="$(lower "$ini")"
    [[ "$lname" == ${prefix}* ]] && out+=("$ini")
  done

  ((${#out[@]})) && printf '%s\n' "${out[@]}" || return 1
}


resolve_scenario_ini(){
  local sel="$(lower "$1")"

  # numeric index (1..N) for main SCENARIOS only (indices stay stable)
  if [[ "$sel" =~ ^[0-9]+$ ]]; then
    local idx="$sel"
    if (( idx>=1 && idx<=${#SCENARIOS[@]} )); then
      echo "${SCENARIOS[$((idx-1))]}"; return 0
    fi
  fi

  # exact match against both arrays
  for ini in "${EXTRA_SCENARIOS_FIRST[@]}"; do [[ "$(lower "$ini")" == "$sel" ]] && { echo "$ini"; return 0; }; done
  for ini in "${SCENARIOS[@]}"; do [[ "$(lower "$ini")" == "$sel" ]] && { echo "$ini"; return 0; }; done

  # fuzzy on hints or ini names (both arrays)
  for ini in "${EXTRA_SCENARIOS_FIRST[@]}"; do
    local hint="$(lower "$ini ${NAME_HINT[X1]-}")"
    [[ "$hint" == *"$sel"* ]] && { echo "$ini"; return 0; }
  done
  for i in "${!SCENARIOS[@]}"; do
    local ini="${SCENARIOS[$i]}"
    local hint="$(lower "${NAME_HINT[$((i+1))]} $ini")"
    [[ "$hint" == *"$sel"* ]] && { echo "$ini"; return 0; }
  done
  return 1
}

latest_result_base(){   # basename (no extension) for newest matching prefix
  local prefix="$1" ext="$2" newest=""
  newest=$(ls -1t "$RESULTS_DIR/${prefix}-s*.$ext" 2>/dev/null | head -1 || true)
  [[ -z "$newest" ]] && newest=$(ls -1t "$RESULTS_DIR/${prefix}.$ext" 2>/dev/null | head -1 || true)
  # this covers names like n1000-gw1-ADR-s0.ini.sca
  [[ -z "$newest" ]] && newest=$(ls -1t "$RESULTS_DIR/${prefix}"*".$ext" 2>/dev/null | head -1 || true)
  [[ -n "$newest" ]] && { newest="${newest%.*}"; basename "$newest"; } || echo ""
}

file_size(){ local f="$1"; [[ -f "$f" ]] && ls -lh "$f" | awk '{print $5}' || echo "0B"; }

# ---------- Core functions
run_scenario(){
  local ini="$1"
  echo ""
  echo "=== RUN: $ini ==="
  ( cd "$EXAMPLES_DIR" && opp_run -u Cmdenv -c General -f "$ini" \
      -n "$NED_PATH" -l ../../src/flora -l ../../../inet4.4/src/INET )
  echo "=== DONE: $ini ==="
}

# run opp_scavetool, keep stdout so we can parse "Exported N ..." / "Export N ..."
# If JSON missing or empty [], delete it and return 1; else print count+size and return 0.
export_with_count(){
  local src="$1"      # .sca or .vec file
  local filter="$2"   # scave filter (quoted)
  local out="$3"      # output json path
  local label="$4"    # label to print (e.g., scalars)

  local log; log="$(mktemp)"

  # Try modern flag first (-F JSON), fall back to older (-f JSON) if needed.
  if ! opp_scavetool export -F JSON -o "$out" -f "$filter" "$src" 2>&1 | tee "$log"; then
    rm -f "$out"
    if ! opp_scavetool export -f JSON -o "$out" -f "$filter" "$src" 2>&1 | tee "$log"; then
      rm -f "$out"; rm -f "$log"; return 1
    fi
  fi

  # If output missing or trivially empty, treat as no data
  if [[ ! -f "$out" ]]; then rm -f "$log"; return 1; fi
  local szb; szb=$(wc -c < "$out" | tr -d '[:space:]')
  if [[ "$szb" -le 4 ]] || grep -q '^\s*\[\s*\]\s*$' "$out"; then
    rm -f "$out"; rm -f "$log"; return 1
  fi

  # Parse count from tool output (handles "Exported 5313 scalars" / "Export 836 histograms")
  local count; count="$(grep -Eo 'Export(ed)?[[:space:]]+[0-9,]+' "$log" | tail -1 | grep -Eo '[0-9,]+' | tr -d ',')"
  rm -f "$log"

  # Print summary
  local hsize; hsize="$(ls -lh "$out" | awk '{print $5}')"
  if [[ -n "$count" ]]; then
    echo "       -> $label: $count items, size $hsize"
  else
    echo "       -> $label: size $hsize"
  fi
  return 0
}

export_scenario(){
  local ini="$1" prefix="${RESULT_PREFIX[$ini]:-}"
  if [[ -z "$prefix" ]]; then echo "  [EXPORT] No known result prefix for '$ini' -> skipping."; return 0; fi

  local base; base="$(latest_result_base "$prefix" sca)"
  [[ -z "$base" ]] && base="$(latest_result_base "$prefix" vec)"
  if [[ -z "$base" ]]; then echo "  [EXPORT] No results for prefix '$prefix' in '$RESULTS_DIR' -> skipping."; return 0; fi

  echo "  [EXPORT] Using result base: $base"
  local SCA="$RESULTS_DIR/${base}.sca"
  local VEC="$RESULTS_DIR/${base}.vec"
  local OUT_SCAL="$OUTPUT_DIR/${base}_scalars.json"
  local OUT_PARAM="$OUTPUT_DIR/${base}_parameters.json"
  local OUT_HIST="$OUTPUT_DIR/${base}_histograms.json"
  local OUT_VEC="$OUTPUT_DIR/${base}_app_vectors.json"

  # 1) Scalars
  echo "    1) scalars ..."
  if [[ -f "$SCA" ]]; then
    if ! export_with_count "$SCA" 'type =~ scalar' "$OUT_SCAL" "scalars"; then
      echo "       .. no scalars (skipped)"
    fi
  else
    echo "       !! .sca not found (skipped)"
  fi

  # 2) Parameters
  echo "    2) parameters ..."
  if [[ -f "$SCA" ]]; then
    if ! export_with_count "$SCA" 'type =~ parameter' "$OUT_PARAM" "parameters"; then
      echo "       .. no parameters (skipped)"
    fi
  else
    echo "       !! .sca not found (skipped)"
  fi

  # 3) Histograms
  echo "    3) histograms ..."
  if [[ -f "$SCA" ]]; then
    if ! export_with_count "$SCA" 'type =~ histogram' "$OUT_HIST" "histograms"; then
      echo "       .. no histograms (skipped)"
    fi
  else
    echo "       !! .sca not found (skipped)"
  fi

  # 4) Vectors (**.app[*])
  echo "    4) app vectors (**.app[*]) ..."
  if [[ -f "$VEC" ]]; then
    if ! export_with_count "$VEC" 'type =~ vector AND module =~ "**.app[*]"' "$OUT_VEC" "vectors(app)"; then
      echo "       .. no vectors for **.app[*] (skipped)"
    fi
  else
    echo "       !! .vec not found (skipped)"
  fi
}

# ---------- Main
echo "FLoRa Runner + Export"
echo "Date: $(date)"
echo "Output dir: $OUTPUT_DIR"
echo "Export: $DO_EXPORT"
echo "INET path: $INET_SRC"
echo "NED path: $NED_PATH"
echo ""

if [[ -n "${SCENARIO_ARG:-}" ]]; then
  # First: does it refer to a whole scenario group (e.g., "scenario-01")?
  if mapfile -t MANY < <(resolve_scenarios_group "$SCENARIO_ARG"); then
    echo "Resolved group '${SCENARIO_ARG}' -> ${#MANY[@]} INIs"
    for ini in "${MANY[@]}"; do
      run_scenario "$ini"
      if $DO_EXPORT; then export_scenario "$ini"; fi
    done
    exit 0
  fi

  # Otherwise: resolve a single scenario by index/name/partial/ini
  ini="$(resolve_scenario_ini "$SCENARIO_ARG")" || { echo "Could not resolve scenario selector: $SCENARIO_ARG"; exit 2; }
  run_scenario "$ini"
  if $DO_EXPORT; then export_scenario "$ini"; fi
  exit 0
fi


# Run the EXTRA first (n1000-gw1-ADR.ini), then the standard list
for ini in "${EXTRA_SCENARIOS_FIRST[@]}"; do
  run_scenario "$ini"
  if $DO_EXPORT; then export_scenario "$ini"; fi
done

for ini in "${SCENARIOS[@]}"; do
  run_scenario "$ini"
  if $DO_EXPORT; then export_scenario "$ini"; fi
done

echo ""
echo "=== ALL DONE ==="
