#!/usr/bin/env bash
# Export JSON for OMNeT++ results.
# Modes:
#   1) No args                  => export ALL .sca/.vec found recursively
#   2) <path/to/file.ini>       => export ONLY newest .sca/.vec for that INI
#   3) <prefix>                 => export ONLY newest .sca/.vec for that prefix
set -euo pipefail

SIM_DIR="$(cd "$(dirname "$0")" && pwd)"   # .../flora/simulations
RESULTS_DIR="$SIM_DIR/results"
ALT_RESULTS_DIR="$SIM_DIR/examples/results"
OUTPUT_DIR_WIN='D:\Doctorat\anul_2\apps\FLoRa_development\flora\simulations\json_exports'
if command -v cygpath >/dev/null 2>&1; then
  OUTPUT_DIR="$(cygpath -u "$OUTPUT_DIR_WIN")"
else
  OUTPUT_DIR="$OUTPUT_DIR_WIN"
fi
mkdir -p "$OUTPUT_DIR"

echo "=== JSON Export ==="
echo "SIM_DIR     : $SIM_DIR"
echo "RESULTS_DIR : $RESULTS_DIR"
echo "ALT_RESULTS : $ALT_RESULTS_DIR"
echo "OUTPUT_DIR  : $OUTPUT_DIR"
echo ""

command -v opp_scavetool >/dev/null 2>&1 || { echo "❌ opp_scavetool not in PATH"; exit 1; }

# -------- helpers --------
detect_result_prefix_from_ini() {
  local ini="$1" line path base
  [[ -f "$ini" ]] || { echo ""; return 1; }

  # Prefer vector, else scalar
  line="$(grep -m1 -E '^[[:space:]]*output-vector-file[[:space:]]*=' "$ini" || true)"
  if [[ -z "$line" ]]; then
    line="$(grep -m1 -E '^[[:space:]]*output-scalar-file[[:space:]]*=' "$ini" || true)"
  fi
  [[ -z "$line" ]] && { echo ""; return 1; }

  # Strip key, quotes, trailing spaces; normalize slashes
  path="$(echo "$line" | sed -E \
          -e 's/^[[:space:]]*output-(vector|scalar)-file[[:space:]]*=[[:space:]]*//' \
          -e 's/[[:space:]]*$//' \
          -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//")"
  path="${path//\\//}"

  # File basename without extension, e.g. scenario-08-baseline-2gw-s${runnumber}_1km
  base="$(basename "$path")"
  base="${base%.vec}"
  base="${base%.sca}"

  # --- CRUCIAL STEP ---
  # Cut at the first occurrence of "-s${" (drop runnumber var and anything after: } or suffixes like _1km)
  if [[ "$base" == *"-s\${"* ]]; then
    base="${base%%-s\$\{*}"
  fi

  # Also handle the rare case of explicit numeric runnumber inside ini (e.g. "-s0")
  # Keep only the part before the first "-s" followed by digits
  if [[ "$base" =~ ^(.+)-s[0-9]+.*$ ]]; then
    base="${BASH_REMATCH[1]}"
  fi

  # Final cleanup of stray braces if any
  base="${base//\}/}"

  echo "$base"
}


latest_result_base_in_root() {
  local prefix="$1" ext="$2" root="$3" newest=""
  [[ -d "$root" ]] || { echo ""; return 0; }
  newest=$(find "$root" -type f -name "${prefix}-s*.${ext}" -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -1 | awk '{sub(/^[0-9.]+ /,"");print}' || true)
  [[ -z "$newest" ]] && newest=$(find "$root" -type f -name "${prefix}.${ext}"     -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -1 | awk '{sub(/^[0-9.]+ /,"");print}' || true)
  [[ -z "$newest" ]] && newest=$(find "$root" -type f -name "${prefix}*.${ext}"    -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -1 | awk '{sub(/^[0-9.]+ /,"");print}' || true)
  [[ -n "$newest" ]] && { newest="${newest%.*}"; echo "$newest"; } || echo ""
}

latest_result_base_any() {
  local prefix="$1" ext="$2" base=""
  base="$(latest_result_base_in_root "$prefix" "$ext" "$RESULTS_DIR")"
  [[ -z "$base" ]] && base="$(latest_result_base_in_root "$prefix" "$ext" "$ALT_RESULTS_DIR")"
  echo "$base"
}

export_one() {
  local src="$1" filter="$2" out="$3" label="$4"
  [[ -f "$src" ]] || { echo "  .. $label: missing"; return; }
  if opp_scavetool export -F JSON -o "$out" -f "$filter" "$src"; then
    local sz="$(ls -lh "$out" | awk '{print $5}')"
    echo "  .. $label → $(basename "$out") ($sz)"
  else
    echo "  .. $label: export failed"
  fi
}

export_for_basepath() {
  local base="$1"
  local dir="$(dirname "$base")"
  local name="$(basename "$base")"
  local SCA=""
  local VEC=""
  for ext in sca SCA; do [[ -f "$dir/$name.$ext" ]] && { SCA="$dir/$name.$ext"; break; }; done
  for ext in vec VEC; do [[ -f "$dir/$name.$ext" ]] && { VEC="$dir/$name.$ext"; break; }; done
  local OUT="$OUTPUT_DIR/$name"
  echo "→ Export: $name"
  [[ -n "$SCA" ]] && export_one "$SCA" 'type =~ scalar'     "${OUT}_scalars.json"     "scalars"
  [[ -n "$SCA" ]] && export_one "$SCA" 'type =~ parameter'  "${OUT}_parameters.json"  "parameters"
  [[ -n "$SCA" ]] && export_one "$SCA" 'type =~ histogram'  "${OUT}_histograms.json"  "histograms"
  [[ -n "$VEC" ]] && export_one "$VEC" 'type =~ vector AND module =~ "**.app[*]"' "${OUT}_app_vectors.json" "app vectors"
  echo ""
}

export_all_recursive() {
  local root="$1"
  [[ -d "$root" ]] || return 0
  declare -A SEEN=()
  while IFS= read -r -d '' f; do
    SEEN["${f%.*}"]=1
  done < <(find "$root" -type f \( -iname '*.sca' -o -iname '*.vec' \) -print0 2>/dev/null)
  for b in "${!SEEN[@]}"; do export_for_basepath "$b"; done
}

# -------- modes --------
ARG="${1:-}"

if [[ -z "$ARG" ]]; then
  echo "Mode: export ALL (recursive)"
  export_all_recursive "$RESULTS_DIR"
  export_all_recursive "$ALT_RESULTS_DIR"
  echo "✅ done."
  exit 0
fi

if [[ -f "$ARG" && "$ARG" == *.ini ]]; then
  # STRICT single-INI mode
  prefix="$(detect_result_prefix_from_ini "$ARG")"
  [[ -z "$prefix" ]] && { echo "❌ cannot parse output-* from ini: $ARG"; exit 2; }
  # find newest .sca/.vec only for this prefix
  base="$(latest_result_base_any "$prefix" sca)"
  [[ -z "$base" ]] && base="$(latest_result_base_any "$prefix" vec)"
  [[ -z "$base" ]] && { echo "❌ no results for prefix '$prefix'"; exit 1; }
  echo "Mode: INI → prefix '$prefix' → base '$(basename "$base")'"
  export_for_basepath "$base"
  echo "✅ done."
  exit 0
fi

# prefix mode
prefix="$ARG"
base="$(latest_result_base_any "$prefix" sca)"
[[ -z "$base" ]] && base="$(latest_result_base_any "$prefix" vec)"
[[ -z "$base" ]] && { echo "❌ no results for prefix '$prefix'"; exit 1; }
echo "Mode: prefix '$prefix' → base '$(basename "$base")'"
export_for_basepath "$base"
echo "✅ done."
