#!/usr/bin/env bash
# Export all JSON variants for a given scenario RUN, auto-detecting result base.
# Usage:
#   ./complete_export_all_scenarios.sh examples/omnetpp-scenario-05-high-traffic.ini
#   ./complete_export_all_scenarios.sh scenario-05-high-traffic-s0
#   ./complete_export_all_scenarios.sh scenario-05-high-traffic

set -euo pipefail

SIM_DIR="$(cd "$(dirname "$0")" && pwd)"
EXAMPLES_DIR="$SIM_DIR/examples"
RESULTS_DIR="$SIM_DIR/results"
OUTPUT_DIR="$SIM_DIR/json_exports"
mkdir -p "$OUTPUT_DIR"

ARG="${1:-}"
if [[ -z "$ARG" ]]; then
  echo "Usage: $0 <ini | base | base-with-run>"
  exit 2
fi

detect_result_prefix_from_ini(){
  local ini="$1" ini_path="$ini"
  [[ -f "$ini_path" ]] || ini_path="$EXAMPLES_DIR/$ini"
  [[ -f "$ini_path" ]] || { echo ""; return 1; }
  local line
  line="$(grep -E '^[[:space:]]*output-vector-file[[:space:]]*=' "$ini_path" || true)"
  [[ -z "$line" ]] && line="$(grep -E '^[[:space:]]*output-scalar-file[[:space:]]*=' "$ini_path" || true)"
  [[ -z "$line" ]] && { echo ""; return 1; }
  local path; path="$(echo "$line" | sed -E 's/^[[:space:]]*output-(vector|scalar)-file[[:space:]]*=[[:space:]]*//; s/[[:space:]]*$//; s/^"//; s/"$//')"
  local base; base="$(basename "$path")"
  base="${base%-s\${runnumber}.vec}"
  base="${base%-s\${runnumber}.sca}"
  base="${base%.vec}"
  base="${base%.sca}"
  echo "$base"
}

latest_result_base(){   # basename (no extension) for newest matching prefix
  local prefix="$1" ext="$2" newest=""
  newest=$(ls -1t "$RESULTS_DIR/${prefix}-s*.$ext" 2>/dev/null | head -1 || true)
  [[ -z "$newest" ]] && newest=$(ls -1t "$RESULTS_DIR/${prefix}.$ext" 2>/dev/null | head -1 || true)
  [[ -z "$newest" ]] && newest=$(ls -1t "$RESULTS_DIR/${prefix}"*".$ext" 2>/dev/null | head -1 || true)
  [[ -n "$newest" ]] && { newest="${newest%.*}"; basename "$newest"; } || echo ""
}

# Resolve base
BASE=""
if [[ "$ARG" == *.ini ]]; then
  BASE="$(detect_result_prefix_from_ini "$ARG")"
else
  BASE="${ARG%-s*}"   # if user passed "...-s0", trim run suffix
fi
if [[ -z "$BASE" ]]; then
  echo "Could not determine result base from '$ARG'"; exit 2
fi

BASE_USE="$(latest_result_base "$BASE" sca)"
[[ -z "$BASE_USE" ]] && BASE_USE="$(latest_result_base "$BASE" vec)"
if [[ -z "$BASE_USE" ]]; then
  echo "No results for base '$BASE' under $RESULTS_DIR"; exit 1
fi

echo "Testing All Export Types for base: $BASE_USE"
echo "============================================"

SCA="$RESULTS_DIR/${BASE_USE}.sca"
VEC="$RESULTS_DIR/${BASE_USE}.vec"

echo "Available data in .sca file:"
[[ -f "$SCA" ]] && opp_scavetool query "$SCA" || echo "  (no .sca file present)"
echo ""

if [[ -f "$SCA" ]]; then
  echo "1. Exporting scalars..."
  if opp_scavetool export -f JSON -o "$OUTPUT_DIR/${BASE_USE}_scalars.json" -f 'type =~ scalar' "$SCA"; then
    SIZE=$(ls -lh "$OUTPUT_DIR/${BASE_USE}_scalars.json" | awk '{print $5}')
    echo "   SUCCESS: ${BASE_USE}_scalars.json ($SIZE)"
  else
    echo "   FAILED"
  fi

  echo "2. Exporting parameters..."
  if opp_scavetool export -f JSON -o "$OUTPUT_DIR/${BASE_USE}_parameters.json" -f 'type =~ parameter' "$SCA"; then
    SIZE=$(ls -lh "$OUTPUT_DIR/${BASE_USE}_parameters.json" | awk '{print $5}')
    echo "   SUCCESS: ${BASE_USE}_parameters.json ($SIZE)"
  else
    echo "   FAILED"
  fi

  echo "3. Exporting histograms..."
  if opp_scavetool export -f JSON -o "$OUTPUT_DIR/${BASE_USE}_histograms.json" -f 'type =~ histogram' "$SCA"; then
    SIZE=$(ls -lh "$OUTPUT_DIR/${BASE_USE}_histograms.json" | awk '{print $5}')
    echo "   SUCCESS: ${BASE_USE}_histograms.json ($SIZE)"
  else
    echo "   FAILED"
  fi

  echo "4. Exporting statistics (if any)..."
  if opp_scavetool export -f JSON -o "$OUTPUT_DIR/${BASE_USE}_statistics.json" -f 'type =~ statistic' "$SCA"; then
    SIZE=$(ls -lh "$OUTPUT_DIR/${BASE_USE}_statistics.json" | awk '{print $5}')
    echo "   SUCCESS: ${BASE_USE}_statistics.json ($SIZE)"
  else
    echo "   No statistics or export failed"
  fi
else
  echo "ERROR: $SCA not found"
fi

echo ""
if [[ -f "$VEC" ]]; then
  echo "5. Exporting app vectors..."
  if opp_scavetool export -f JSON -o "$OUTPUT_DIR/${BASE_USE}_app_vectors.json" -f 'type =~ vector AND module =~ "**.app[*]"' "$VEC"; then
    SIZE=$(ls -lh "$OUTPUT_DIR/${BASE_USE}_app_vectors.json" | awk '{print $5}')
    echo "   SUCCESS: ${BASE_USE}_app_vectors.json ($SIZE)"
  else
    echo "   App filter failed, trying broader pattern..."
    if opp_scavetool export -f JSON -o "$OUTPUT_DIR/${BASE_USE}_app_vectors.json" -f 'type =~ vector AND module =~ "*app*"' "$VEC"; then
      SIZE=$(ls -lh "$OUTPUT_DIR/${BASE_USE}_app_vectors.json" | awk '{print $5}')
      echo "   SUCCESS: ${BASE_USE}_app_vectors.json ($SIZE, broad filter)"
    else
      echo "   FAILED"
    fi
  fi
else
  echo "ERROR: $VEC not found"
fi

echo ""
echo "JSON written under: $OUTPUT_DIR"
ls -la "$OUTPUT_DIR"/"${BASE_USE}"_*.json 2>/dev/null || true
