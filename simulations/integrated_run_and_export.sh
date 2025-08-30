#!/usr/bin/env bash
# FLoRa: run scenarios + export JSON (no empty files; print counts & sizes)
# - Two functions: run_scenario, export_scenario
# - Default: run each scenario, then export {scalars, parameters, histograms, app vectors}
# - --export=false / --no-export: skip exports
# - --scenario <N|name|ini>: run/export only that scenario (1..8, partial name, or full ini)

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

SCENARIOS=(
  "omnetpp-scenario-01-01_fixed_baseline.ini"  # 1
  "omnetpp-scenario-01-02_sf_only.ini"         # 2
  "omnetpp-scenario-01-03_tp_only.ini"         # 3
  "omnetpp-scenario-01-04_no_init.ini"         # 4
  "omnetpp-scenario-01-05_adr_sf_init.ini"     # 5
  "omnetpp-scenario-01-06_adr_tp_init.ini"     # 6
  "omnetpp-scenario-01-07_adr_both_init.ini"   # 7
  "omnetpp-scenario-01-08_adr_no_init.ini"     # 8
)
declare -A RESULT_PREFIX=(
  ["omnetpp-scenario-01-01_fixed_baseline.ini"]="scenario-01-baseline-01_fixed_baseline"
  ["omnetpp-scenario-01-02_sf_only.ini"]="scenario-01-baseline-02_sf_only"
  ["omnetpp-scenario-01-03_tp_only.ini"]="scenario-01-baseline-03_tp_only"
  ["omnetpp-scenario-01-04_no_init.ini"]="scenario-01-baseline-04_no_init"
  ["omnetpp-scenario-01-05_adr_sf_init.ini"]="scenario-01-baseline-05_adr_sf_init"
  ["omnetpp-scenario-01-06_adr_tp_init.ini"]="scenario-01-baseline-06_adr_tp_init"
  ["omnetpp-scenario-01-07_adr_both_init.ini"]="scenario-01-baseline-07_adr_both_init"
  ["omnetpp-scenario-01-08_adr_no_init.ini"]="scenario-01-baseline-08_adr_no_init"
)
declare -A NAME_HINT=(
  [1]="01_fixed_baseline baseline"
  [2]="02_sf_only sf_only"
  [3]="03_tp_only tp_only"
  [4]="04_no_init no_init"
  [5]="05_adr_sf_init adr_sf_init"
  [6]="06_adr_tp_init adr_tp_init"
  [7]="07_adr_both_init adr_both_init"
  [8]="08_adr_no_init adr_no_init"
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
resolve_scenario_ini(){
  local sel="$(lower "$1")"
  [[ "$sel" =~ ^[1-8]$ ]] && { echo "${SCENARIOS[$((sel-1))]}"; return 0; }
  for ini in "${SCENARIOS[@]}"; do [[ "$(lower "$ini")" == "$sel" ]] && { echo "$ini"; return 0; }; done
  for i in {1..8}; do local ini="${SCENARIOS[$((i-1))]}"; local hint="$(lower "${NAME_HINT[$i]} $ini")"; [[ "$hint" == *"$sel"* ]] && { echo "$ini"; return 0; }; done
  return 1
}
latest_result_base(){   # basename (no extension) for newest matching prefix
  local prefix="$1" ext="$2" newest=""
  newest=$(ls -1t "$RESULTS_DIR/${prefix}-s*.$ext" 2>/dev/null | head -1 || true)
  [[ -z "$newest" ]] && newest=$(ls -1t "$RESULTS_DIR/${prefix}.$ext" 2>/dev/null | head -1 || true)
  [[ -z "$newest" ]] && newest=$(ls -1t "$RESULTS_DIR/${prefix}"*".$ext" 2>/dev/null | head -1 || true)
  [[ -n "$newest" ]] && { newest="${newest%.*}"; basename "$newest"; } || echo ""
}
file_size(){ local f="$1"; [[ -f "$f" ]] && ls -lh "$f" | awk '{print $5}' || echo "0B"; }

# run opp_scavetool, keep stdout so we can parse "Exported N ..." / "Export N ..."
# If no JSON (or empty '[]'), remove the file and return 1; else print count & size and return 0.
export_with_count(){
  local src="$1" filter="$2" out="$3" label="$4"
  local log; log="$(mktemp)"
  if ! opp_scavetool export -f JSON -o "$out" -f "$filter" "$src" 2>&1 | tee "$log"; then
    rm -f "$out"; rm -f "$log"; return 1
  fi

  # Delete if missing or trivially empty
  if [[ ! -f "$out" ]]; then rm -f "$log"; return 1; fi
  local szb; szb=$(wc -c < "$out" | tr -d '[:space:]')
  if [[ "$szb" -le 4 ]] || grep -q '^\s*\[\s*\]\s*$' "$out"; then
    rm -f "$out"; rm -f "$log"; return 1
  fi

  # Parse count from tool output (handles "Exported 5313 scalars" / "Export 836 histograms")
  local count; count="$(grep -Eo 'Export(ed)?[[:space:]]+[0-9,]+' "$log" | tail -1 | grep -Eo '[0-9,]+' | tr -d ',')"
  rm -f "$log"

  # Print summary
  local hsize; hsize="$(file_size "$out")"
  if [[ -n "$count" ]]; then
    echo "       -> $label: $count items, size $hsize"
  else
    echo "       -> $label: size $hsize"
  fi
  return 0
}

# ---------- The two functions
run_scenario(){
  local ini="$1"
  echo ""
  echo "=== RUN: $ini ==="
  ( cd "$EXAMPLES_DIR" && opp_run -u Cmdenv -c General -f "$ini" \
      -n "$NED_PATH" -l ../../src/flora -l ../../../inet4.4/src/INET )
  echo "=== DONE: $ini ==="
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
  ini="$(resolve_scenario_ini "$SCENARIO_ARG")" || { echo "Could not resolve scenario: $SCENARIO_ARG"; exit 2; }
  run_scenario "$ini"
  $DO_EXPORT && export_scenario "$ini"
  exit 0
fi

for ini in "${SCENARIOS[@]}"; do
  run_scenario "$ini"
  $DO_EXPORT && export_scenario "$ini"
done

echo ""
echo "All done."
