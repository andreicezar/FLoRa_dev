#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Scenario-07 Analyzer (Propagation Models) for OMNeT++/FLoRa - FIXED VERSION
# - Analyzes propagation model performance: LogDistance vs FreeSpace
# - Extracts RSSI/SNR statistics from histograms and vectors
# - Performs distance-based analysis for comparison with ns-3
# - FIXES: File discovery logic and adds validation

from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Iterable
import argparse, json, re, math, statistics
import pandas as pd
import math

# =============================================================================
# Key tracking (same as Scenario-05)
# =============================================================================
USED_KEYS: Dict[str, set] = {
    "parameters": set(), "scalars": set(), "histograms": set(), "vectors": set()
}

def _used_param(name: str) -> None:
    if name: USED_KEYS["parameters"].add(str(name))

def _used_scalar(name: str) -> None:
    if name: USED_KEYS["scalars"].add(str(name))

def _used_hist(name: str) -> None:
    if name: USED_KEYS["histograms"].add(str(name))

def _used_vector(name: str) -> None:
    if name: USED_KEYS["vectors"].add(str(name))

def print_used_keys() -> None:
    print("\n=== Used keys (this run) ===")
    for data_type in ["parameters", "scalars", "histograms", "vectors"]:
        if USED_KEYS[data_type]:
            print(f"{data_type.capitalize()}:")
            for k in sorted(USED_KEYS[data_type]): 
                print(f"  - {k}")
        else: 
            print(f"{data_type.capitalize()}: (none)")

def dump_used_keys(path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump({k: sorted(v) for k, v in USED_KEYS.items()}, f, ensure_ascii=False, indent=2)
    print(f"[keys] Saved to: {path}")

# =============================================================================
# JSON helpers (same as Scenario-05)
# =============================================================================
def read_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _get_block(obj: Any, key: str) -> Optional[dict]:
    if isinstance(obj, dict):
        if key in obj and isinstance(obj[key], list):
            return obj
        for v in obj.values():
            if isinstance(v, dict) and key in v and isinstance(v[key], list):
                return v
    return None

def get_parameters_list(obj: Any) -> List[dict]:
    blk = _get_block(obj, "parameters")
    return blk.get("parameters", []) if blk else []

def get_scalars_list(obj: Any) -> List[dict]:
    blk = _get_block(obj, "scalars")
    return blk.get("scalars", []) if blk else []

def get_histograms_list(obj: Any) -> List[dict]:
    blk = _get_block(obj, "histograms")
    if blk and "histograms" in blk and isinstance(blk["histograms"], list):
        return blk["histograms"]
    blk = _get_block(obj, "statistics")
    if blk and "statistics" in blk and isinstance(blk["statistics"], list):
        return blk["statistics"]
    if isinstance(obj, dict):
        if isinstance(obj.get("histograms"), list): return obj["histograms"]
        if isinstance(obj.get("statistics"), list): return obj["statistics"]
    return []

def get_vectors_list(obj: Any) -> List[dict]:
    for key in ("vectors", "app_vectors"):
        blk = _get_block(obj, key)
        if blk and isinstance(blk.get(key), list):
            return blk[key]
        if isinstance(obj, dict) and isinstance(obj.get(key), list):
            return obj[key]
    return []

# =============================================================================
# Parsing helpers (same as Scenario-05)
# =============================================================================
_TIME_RX = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([a-zA-Z]+)?\s*$")
def parse_time_to_seconds(s: str) -> Optional[float]:
    if s is None: return None
    if isinstance(s, (int, float)): return float(s)
    m = _TIME_RX.match(str(s))
    val = float(m.group(1)) if m else None
    if val is None: return None
    unit = (m.group(2) or "").lower()
    if unit in ("", "s", "sec", "secs", "second", "seconds"): return val
    if unit in ("ms", "msec", "millisecond", "milliseconds"): return val/1000.0
    if unit in ("min", "m", "minute", "minutes"): return val*60.0
    if unit in ("h", "hr", "hour", "hours"): return val*3600.0
    return None

_NUM_RX = re.compile(r"[-+]?[0-9]+(?:\.[0-9]+)?")
def parse_float_from_text(s: str) -> Optional[float]:
    if s is None: return None
    if isinstance(s, (int, float)): return float(s)
    m = _NUM_RX.search(str(s))
    return float(m.group(0)) if m else None

def parse_bool_text(s: str) -> Optional[bool]:
    if isinstance(s, bool): return s
    if s is None: return None
    t = str(s).strip().lower()
    if t in ("true", "yes", "1", "on"): return True
    if t in ("false", "no", "0", "off"): return False
    return None

# =============================================================================
# FIXED File discovery logic
# =============================================================================
def find_bundle_fixed(json_dir: Path, base_name: str) -> Dict[str, Path]:
    """
    FIXED: Find files that exactly match the base configuration name.
    This replaces the flawed token-based matching.
    """
    out: Dict[str, Path] = {}
    print(f"  Looking for files matching: {base_name}_*")
    
    found_files = []
    for p in json_dir.glob(f"{base_name}_*.json"):
        found_files.append(p.name)
        name_lower = p.name.lower()
        
        if "parameters" in name_lower and "parameters" not in out: 
            out["parameters"] = p
        elif "scalars" in name_lower and "scalars" not in out: 
            out["scalars"] = p
        elif ("histograms" in name_lower or "statistics" in name_lower) and "histograms" not in out: 
            out["histograms"] = p
        elif "app_vectors" in name_lower and "app_vectors" not in out: 
            out["app_vectors"] = p
        elif "vectors" in name_lower and "app_vectors" not in out: 
            out["app_vectors"] = p
    
    print(f"  Found files: {found_files}")
    print(f"  Bundle: {list(out.keys())}")
    return out

def find_all_bundles_s07_fixed(json_dir: Path) -> List[Tuple[str, Dict[str, Path]]]:
    """
    FIXED: Find every sub-scenario for scenario-07 using exact name matching.
    """
    # Find all unique base names by removing the file type suffix
    bases = set()
    for p in json_dir.glob("*.json"):
        name = p.name
        low = name.lower()
        if "scenario-07" in low and any(model in low for model in ["logdist", "freespace"]):
            # Remove the file type suffix to get the base name
            base = re.sub(r"_(parameters|scalars|histograms|statistics|app_vectors|vectors|extracted)\.json$", "", name, flags=re.I)
            bases.add(base)
    
    print(f"Found {len(bases)} unique base configurations:")
    for base in sorted(bases):
        print(f"  - {base}")
    
    out: List[Tuple[str, Dict[str, Path]]] = []
    for base in sorted(bases):
        bundle = find_bundle_fixed(json_dir, base)
        if bundle.get("parameters") and bundle.get("scalars"):
            out.append((base, bundle))
            print(f"  ✓ Valid bundle: {base}")
        else:
            print(f"  ✗ Incomplete bundle: {base} (missing parameters or scalars)")
    
    return out

# =============================================================================
# IMPROVED Propagation model inference
# =============================================================================
def infer_propagation_model_from_label(label: str) -> Tuple[str, Optional[float]]:
    """IMPROVED: Better handling of path loss exponent extraction."""
    name = label.lower()
    
    # Check for LogDistance with path loss exponent
    logdist_patterns = [
        (r"logdist[_-]?(\d+\.?\d*)", "LogDistance"),
        (r"log[_-]?distance[_-]?(\d+\.?\d*)", "LogDistance"),
    ]
    
    for pattern, model_type in logdist_patterns:
        match = re.search(pattern, name)
        if match:
            try:
                exponent_str = match.group(1)
                
                # IMPROVED: Better handling of different number formats
                if "." in exponent_str:
                    # Already has decimal point
                    exponent = float(exponent_str)
                elif len(exponent_str) == 2:
                    # Two digits like "32" -> 3.2
                    exponent = float(exponent_str[0] + "." + exponent_str[1])
                elif len(exponent_str) == 3:
                    # Three digits like "376" -> 3.76
                    exponent = float(exponent_str[0] + "." + exponent_str[1:])
                else:
                    # Single digit or more than 3 digits, use as-is
                    exponent = float(exponent_str)
                
                return model_type, exponent
            except ValueError:
                continue
    
    # Check for FreeSpace/Friis
    freespace_patterns = ["freespace", "friis", "free_space"]
    for pattern in freespace_patterns:
        if pattern in name:
            return "FreeSpace", None
    
    # Default fallback
    return "Unknown", None

# =============================================================================
# Enhanced RSSI/SNR analysis functions (same as original)
# =============================================================================
def _hist_stat(entry: dict, field: str) -> Optional[float]:
    stat = entry.get("stat")
    if isinstance(stat, dict) and field in stat:
        try: return float(stat[field])
        except Exception: return None
    return None

def extract_rssi_snr_stats(histograms: List[dict], vectors: List[dict]) -> Dict[str, Optional[float]]:
    """Extract comprehensive RSSI and SNR statistics."""
    stats = {}
    
    # RSSI from histograms
    rssi_patterns = [re.compile(r"\breceivedRSSI\b", re.I), re.compile(r"\bRSSI\b", re.I)]
    for h in histograms:
        nm = h.get("name", "") or ""
        if any(rx.search(nm) for rx in rssi_patterns):
            _used_hist(nm)
            stats["rssi_mean_hist"] = _hist_stat(h, "mean")
            stats["rssi_min_hist"] = _hist_stat(h, "min")
            stats["rssi_max_hist"] = _hist_stat(h, "max")
            stats["rssi_std_hist"] = _hist_stat(h, "stddev")
            stats["rssi_count_hist"] = _hist_stat(h, "count")
            break
    
    # SNR from histograms  
    snr_patterns = [re.compile(r"\bminSnir\b", re.I), re.compile(r"\bSNIR\b", re.I), re.compile(r"\bSNR\b", re.I)]
    for h in histograms:
        nm = h.get("name", "") or ""
        if any(rx.search(nm) for rx in snr_patterns):
            _used_hist(nm)
            stats["snr_mean_hist"] = _hist_stat(h, "mean")
            stats["snr_min_hist"] = _hist_stat(h, "min")
            stats["snr_max_hist"] = _hist_stat(h, "max")
            stats["snr_std_hist"] = _hist_stat(h, "stddev")
            stats["snr_count_hist"] = _hist_stat(h, "count")
            break
    
    # RSSI from vectors
    rssi_vec_patterns = [re.compile(r"\bVector of RSSI per node\b", re.I), re.compile(r"\bRSSI\b", re.I)]
    rssi_values = []
    for v in vectors:
        nm = v.get("name", "") or ""
        if any(rx.search(nm) for rx in rssi_vec_patterns):
            _used_vector(nm)
            series = _extract_vector_values(v)
            if series:
                rssi_values.extend(series)
    
    if rssi_values:
        stats["rssi_mean_vec"] = statistics.mean(rssi_values)
        stats["rssi_min_vec"] = min(rssi_values)
        stats["rssi_max_vec"] = max(rssi_values)
        stats["rssi_std_vec"] = statistics.stdev(rssi_values) if len(rssi_values) > 1 else 0
        stats["rssi_count_vec"] = len(rssi_values)
    
    # SNR from vectors
    snr_vec_patterns = [re.compile(r"\bVector of SNIR per node\b", re.I), re.compile(r"\bSNIR\b", re.I)]
    snr_values = []
    for v in vectors:
        nm = v.get("name", "") or ""
        if any(rx.search(nm) for rx in snr_vec_patterns):
            _used_vector(nm)
            series = _extract_vector_values(v)
            if series:
                snr_values.extend(series)
    
    if snr_values:
        stats["snr_mean_vec"] = statistics.mean(snr_values)
        stats["snr_min_vec"] = min(snr_values)
        stats["snr_max_vec"] = max(snr_values)
        stats["snr_std_vec"] = statistics.stdev(snr_values) if len(snr_values) > 1 else 0
        stats["snr_count_vec"] = len(snr_values)
    
    return stats

def _extract_vector_values(entry: dict) -> Optional[List[float]]:
    """Extract numeric values from vector entry."""
    for valkey in ("y", "values_y", "vecvalue", "value", "values", "data", "v"):
        arr = entry.get(valkey)
        if isinstance(arr, list) and arr and all(not isinstance(x, (list, tuple, dict)) for x in arr):
            out = []
            for x in arr:
                try: out.append(float(x))
                except Exception: pass
            if out: return out
    
    # Try time-value pairs
    for tkey, vkey in (("time","value"),("t","v"),("vectime","vecvalue"),("x","y")):
        varr = entry.get(vkey)
        if isinstance(varr, list) and varr:
            out = []
            for x in varr:
                try: out.append(float(x))
                except Exception: pass
            if out: return out
    
    # Try nested values
    vals = entry.get("values")
    if isinstance(vals, list) and vals:
        out = []
        for item in vals:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                try: out.append(float(item[1]))
                except Exception: pass
            elif isinstance(item, dict):
                for k in ("v","value","y"):
                    if k in item:
                        try: out.append(float(item[k]))
                        except Exception: pass
                        break
        if out: return out
    
    return None

# =============================================================================
# Standard metric extraction functions (same as original)
# =============================================================================
PARAM_RX = {
    "nodes": [re.compile(r"\bnumberOfNodes\b", re.I)],
    "send_interval": [re.compile(r"\btimeToNextPacket\b", re.I), re.compile(r"\bsendInterval\b", re.I)],
    "initial_sf": [re.compile(r"\binitialLoRaSF\b", re.I)],
    "initial_tp": [re.compile(r"\binitialLoRaTP\b", re.I)],
    "sigma": [re.compile(r"\bsigma\b", re.I)],
    "gamma": [re.compile(r"\bgamma\b", re.I)],  # ← Add this line
}

SCALAR_RX = {
    "total_received": [re.compile(r"\btotalReceivedPackets\b", re.I), re.compile(r"\bLoRa_ServerPacketReceived:count\b", re.I)],
    "sent_primary": [re.compile(r"^sentPackets$", re.I), re.compile(r"^packetsSent$", re.I)],
    "sim_time": [re.compile(r"\bsimulated time\b", re.I)],
}

SERVER_MOD = re.compile(r"LoRaNetworkTest\.networkServer\.app\[0\]", re.I)
NODE_APP_MOD_RX = re.compile(r".*\.loRaNodes\[\d+\]\.app\[0\]$", re.I)

def find_param_by_alias(params: Iterable[Dict[str, Any]], alias_list: List[re.Pattern]) -> Optional[str]:
    for rx in alias_list:
        for p in params:
            nm = str(p.get("name",""))
            if rx.search(nm):
                _used_param(nm)
                return str(p.get("value",""))
    return None

def pick_scalar_by_alias(scalars: Iterable[Dict[str, Any]], alias_list: List[re.Pattern], module_rx: Optional[re.Pattern]=None) -> Optional[float]:
    for rx in alias_list:
        for s in scalars:
            nm = str(s.get("name","")); mod = str(s.get("module",""))
            if module_rx is not None and not module_rx.search(mod): continue
            if rx.search(nm) and s.get("value") is not None:
                _used_scalar(nm)
                try: return float(s["value"])
                except Exception:
                    v = parse_float_from_text(s["value"])
                    if v is not None: return float(v)
    return None

def sum_sent_packets_unique(scalars: List[dict]) -> int:
    """Sum unique sent packets across all nodes."""
    per_module: Dict[str, float] = {}
    for s in scalars:
        mod = s.get("module","") or ""
        nm = s.get("name","") or ""
        v = s.get("value", None)
        if v is None or not NODE_APP_MOD_RX.fullmatch(mod): continue
        if any(rx.fullmatch(nm) for rx in SCALAR_RX["sent_primary"]):
            if mod not in per_module:
                per_module[mod] = float(v)
                _used_scalar(nm)
    return int(sum(per_module.values()))

def validate_propagation_parameters(params: List[dict], label: str) -> None:
    """Validate that propagation parameters are being set correctly."""
    print(f"\n=== PARAMETER VALIDATION: {label} ===")
    
    # Check for gamma parameter
    gamma = find_param_by_alias(params, PARAM_RX["gamma"])
    if gamma is not None:
        print(f"  ✓ gamma found: {gamma}")
    else:
        print(f"  ✗ gamma NOT found - using default value!")
    
    # Check for sigma consistency
    sigma = find_param_by_alias(params, PARAM_RX["sigma"])
    if sigma is not None:
        print(f"  ✓ sigma found: {sigma}")
    else:
        print(f"  ✗ sigma NOT found")
    
    # List all path loss related parameters
    path_loss_params = []
    for p in params:
        param_name = str(p.get("name", ""))
        if "pathLoss" in param_name or "gamma" in param_name.lower() or "alpha" in param_name.lower():
            path_loss_params.append(f"{param_name} = {p.get('value', 'N/A')}")
    
    if path_loss_params:
        print(f"  Path loss parameters found:")
        for param in path_loss_params:
            print(f"    - {param}")
    else:
        print(f"  ✗ No path loss parameters found!")

# =============================================================================
# ENHANCED Analysis functions with validation
# =============================================================================
def analyze_config(bundle: Dict[str, Path], label: str) -> Dict[str, Any]:
    """ENHANCED: Analyze a single propagation model configuration with validation."""
    print(f"\n=== ANALYZING: {label} ===")
    
    # Display which files are being read
    for file_type, path in bundle.items():
        print(f"  Reading {file_type}: {path.name}")
    
    res: Dict[str, Any] = {"Configuration": label}
    
    # Load JSON files
    params_json = read_json(bundle["parameters"]) if "parameters" in bundle else {}
    scalars_json = read_json(bundle["scalars"]) if "scalars" in bundle else {}
    histograms_json = read_json(bundle["histograms"]) if "histograms" in bundle else {}
    vectors_json = read_json(bundle["app_vectors"]) if "app_vectors" in bundle else {}
    
    params = get_parameters_list(params_json)
    scalars = get_scalars_list(scalars_json)
    histograms = get_histograms_list(histograms_json)
    vectors = get_vectors_list(vectors_json)
    
    validate_propagation_parameters(params, label)

    print(f"  Loaded: {len(params)} params, {len(scalars)} scalars, {len(histograms)} histograms, {len(vectors)} vectors")
    
    gamma_param = find_param_by_alias(params, PARAM_RX["gamma"])
    if gamma_param is not None:
        gamma_val = parse_float_from_text(gamma_param)
        if gamma_val is not None:
            res["PathLossExp"] = float(gamma_val)
            print(f"  Extracted gamma from params: {gamma_val}")
    
    # Fallback to label inference if parameter not found
    if "PathLossExp" not in res:
        _, path_loss_exp = infer_propagation_model_from_label(label)
        res["PathLossExp"] = path_loss_exp
        print(f"  Inferred gamma from label: {path_loss_exp}")
    
    # Propagation model type (keep the existing logic)
    prop_model, _ = infer_propagation_model_from_label(label)
    res["PropagationModel"] = prop_model
    
    # Path loss sigma from parameters
    sigma = find_param_by_alias(params, PARAM_RX["sigma"])
    if sigma is not None:
        sigma_val = parse_float_from_text(sigma)
        if sigma_val is not None:
            res["Sigma_dB"] = float(sigma_val)
            print(f"  Sigma from params: {sigma_val} dB")
    
    # Basic parameters
    v = find_param_by_alias(params, PARAM_RX["nodes"])
    if v is not None: res["Nodes"] = int(parse_float_from_text(v) or 0)
    
    v = find_param_by_alias(params, PARAM_RX["send_interval"])
    iv = parse_time_to_seconds(v) if v is not None else None
    if iv is not None: res["Interval_s"] = float(iv)
    
    v = find_param_by_alias(params, PARAM_RX["initial_sf"])
    if v is not None:
        n = parse_float_from_text(v)
        if n is not None: res["Initial SF"] = int(n)
    
    v = find_param_by_alias(params, PARAM_RX["initial_tp"])
    if v is not None:
        n = parse_float_from_text(v)
        if n is not None: res["Initial TP (dBm)"] = float(n)
    
    # Simulation time
    st = pick_scalar_by_alias(scalars, SCALAR_RX["sim_time"])
    if st is not None:
        res["SimTime_s"] = float(st)
        res["SimTime_min"] = float(st) / 60.0
    
    # Packet statistics
    total_sent = sum_sent_packets_unique(scalars)
    if total_sent == 0:
        v = pick_scalar_by_alias(scalars, SCALAR_RX["sent_primary"])
        if v is not None: total_sent = int(v)
    res["Sent"] = int(total_sent)
    
    tr = pick_scalar_by_alias(scalars, SCALAR_RX["total_received"], module_rx=SERVER_MOD)
    if tr is None: tr = pick_scalar_by_alias(scalars, SCALAR_RX["total_received"])
    if tr is not None: res["Received"] = int(tr)
    
    if res.get("Sent", 0) > 0 and isinstance(res.get("Received"), int):
        res["PDR(%)"] = 100.0 * res["Received"] / res["Sent"]
        res["Dropped"] = int(res["Sent"] - res["Received"])
    
    print(f"  Packets: {res.get('Sent', 0)} sent, {res.get('Received', 0)} received, PDR: {res.get('PDR(%)', 0):.2f}%")
    
    # RSSI/SNR analysis
    rf_stats = extract_rssi_snr_stats(histograms, vectors)
    
    # Use histogram stats as primary, vector stats as fallback
    res["AvgRSSI(dBm)"] = rf_stats.get("rssi_mean_hist") or rf_stats.get("rssi_mean_vec")
    res["RSSI_Min(dBm)"] = rf_stats.get("rssi_min_hist") or rf_stats.get("rssi_min_vec")
    res["RSSI_Max(dBm)"] = rf_stats.get("rssi_max_hist") or rf_stats.get("rssi_max_vec")
    res["RSSI_Std"] = rf_stats.get("rssi_std_hist") or rf_stats.get("rssi_std_vec")
    
    res["AvgSNR(dB)"] = rf_stats.get("snr_mean_hist") or rf_stats.get("snr_mean_vec")
    res["SNR_Min(dB)"] = rf_stats.get("snr_min_hist") or rf_stats.get("snr_min_vec")
    res["SNR_Max(dB)"] = rf_stats.get("snr_max_hist") or rf_stats.get("snr_max_vec")
    res["SNR_Std"] = rf_stats.get("snr_std_hist") or rf_stats.get("snr_std_vec")
    
    # Sample counts
    rssi_samples = rf_stats.get("rssi_count_hist") or rf_stats.get("rssi_count_vec")
    snr_samples = rf_stats.get("snr_count_hist") or rf_stats.get("snr_count_vec")
    if rssi_samples: res["RSSI_Samples"] = int(rssi_samples)
    if snr_samples: res["SNR_Samples"] = int(snr_samples)
    
    avg_rssi = res.get("AvgRSSI(dBm)")
    if avg_rssi is not None:
        print(f"  RSSI: avg={avg_rssi:.2f} dBm")
    else:
        print(f"  RSSI: No data found")
    
    print(f"  Analysis complete for {label}")
    return res

def print_parameter_comparison(rows: List[Dict[str, Any]]):
    """Print comparison of expected vs actual parameters."""
    print(f"\n=== PARAMETER VERIFICATION ===")
    print(f"{'Configuration':<35} {'Expected γ':<12} {'Actual γ':<12} {'Status':<10}")
    print("-" * 75)
    
    for row in rows:
        config = row.get("Configuration", "")
        actual_gamma = row.get("PathLossExp", "N/A")
        
        # Extract expected gamma from filename
        _, expected_gamma = infer_propagation_model_from_label(config)
        
        if expected_gamma is not None and actual_gamma != "N/A":
            status = "✓ MATCH" if abs(float(actual_gamma) - expected_gamma) < 0.01 else "✗ MISMATCH"
        else:
            status = "✗ MISSING"
        
        print(f"{config:<35} {expected_gamma or 'N/A':<12} {actual_gamma:<12} {status:<10}")

# =============================================================================
# Output formatting (same as original)
# =============================================================================
def print_propagation_scoreboard(rows: List[Dict[str, Any]], title="SCENARIO 07 - Propagation Model Testing (OMNeT++ FLoRa) - FIXED"):
    if not rows:
        print("No rows to display.")
        return
    
    hdr = (
        "Configuration", "Model", "PathLoss", "Nodes", "PDR(%)", "Sent", "Received",
        "AvgRSSI(dBm)", "RSSI_Min", "RSSI_Max", "AvgSNR(dB)", "SNR_Min", "SNR_Max", "Sigma_dB"
    )
    
    fmt = (
        f"{{:<32}} "          # Configuration  
        f"{{:<13}} "         # Model
        f"{{:>8}} "          # PathLoss
        f"{{:>5}} "          # Nodes
        f"{{:>6}} "          # PDR(%)
        f"{{:>8}} "          # Sent
        f"{{:>9}} "          # Received
        f"{{:>12}} "         # AvgRSSI(dBm)
        f"{{:>9}} "          # RSSI_Min
        f"{{:>9}} "          # RSSI_Max
        f"{{:>10}} "         # AvgSNR(dB)
        f"{{:>7}} "          # SNR_Min
        f"{{:>7}} "          # SNR_Max
        f"{{:>8}}"           # Sigma_dB
    )
    
    def fnum(v, d=2):
        return f"{v:.{d}f}" if isinstance(v, (int, float)) else "NA"
    
    def fint(v):
        return f"{int(v):d}" if isinstance(v, (int, float)) else "NA"
    
    def fmodel(model, exp):
        if exp is not None:
            return f"{model}({exp})"[:13]
        return f"{model}"[:13]
    
    header_line = fmt.format(*hdr)
    line = "-" * len(header_line)
    print("\n" + "=" * len(header_line))
    print(title)
    print("=" * len(header_line))
    print(header_line)
    print(line)
    
    # Sort by propagation model, then path loss exponent
    rows_sorted = sorted(rows, key=lambda r: (
        r.get("PropagationModel", ""), 
        r.get("PathLossExp") or 0
    ))
    
    for r in rows_sorted:
        print(fmt.format(
            r.get("Configuration",""),
            fmodel(r.get("PropagationModel", ""), r.get("PathLossExp")),
            fnum(r.get("PathLossExp")) if r.get("PathLossExp") is not None else "NA",
            fint(r.get("Nodes")),
            fnum(r.get("PDR(%)")),
            fint(r.get("Sent")),
            fint(r.get("Received")),
            fnum(r.get("AvgRSSI(dBm)")),
            fnum(r.get("RSSI_Min(dBm)")),
            fnum(r.get("RSSI_Max(dBm)")),
            fnum(r.get("AvgSNR(dB)")),
            fnum(r.get("SNR_Min(dB)")),
            fnum(r.get("SNR_Max(dB)")),
            fnum(r.get("Sigma_dB")),
        ))
    print("=" * len(header_line))

def print_detailed_analysis(rows: List[Dict[str, Any]]):
    """Print detailed propagation model comparison."""
    if not rows:
        return
    
    print("\n" + "=" * 80)
    print("DETAILED PROPAGATION MODEL ANALYSIS")
    print("=" * 80)
    
    # Group by model type
    models = {}
    for row in rows:
        model = row.get("PropagationModel", "Unknown")
        if model not in models:
            models[model] = []
        models[model].append(row)
    
    for model, model_rows in models.items():
        print(f"\n{model} Model:")
        print("-" * 40)
        
        if model == "LogDistance":
            # Sort by path loss exponent
            model_rows.sort(key=lambda r: r.get("PathLossExp", 0))
            for row in model_rows:
                exp = row.get("PathLossExp")
                pdr = row.get("PDR(%)", 0)
                avg_rssi = row.get("AvgRSSI(dBm)")
                sigma = row.get("Sigma_dB")
                rssi_str = f"{avg_rssi:6.2f}dBm" if avg_rssi is not None else "NA"
                sigma_str = f"{sigma:.1f}dB" if sigma is not None else "NA"
                print(f"  n={exp:4.2f}: PDR={pdr:6.2f}%, AvgRSSI={rssi_str}, sigma={sigma_str}")
        else:
            for row in model_rows:
                pdr = row.get("PDR(%)", 0)
                avg_rssi = row.get("AvgRSSI(dBm)")
                rssi_str = f"{avg_rssi:6.2f}dBm" if avg_rssi is not None else "NA"
                print(f"  PDR={pdr:6.2f}%, AvgRSSI={rssi_str}")
    
    # Best performing model analysis - more robust handling
    valid_rows = [r for r in rows if isinstance(r.get("PDR(%)"), (int, float))]
    if valid_rows:
        best_pdr = max(valid_rows, key=lambda r: r.get("PDR(%)", 0))
        
        # Find best RSSI more safely
        rssi_rows = []
        for r in valid_rows:
            rssi = r.get("AvgRSSI(dBm)")
            if isinstance(rssi, (int, float)):
                rssi_rows.append((r, rssi))
        
        print(f"\nBEST PERFORMERS:")
        print(f"  Best PDR: {best_pdr.get('PropagationModel')} "
              f"({best_pdr.get('PathLossExp', 'N/A')}) = {best_pdr.get('PDR(%)', 0):.2f}%")
        
        if rssi_rows:
            best_rssi_row, best_rssi_val = max(rssi_rows, key=lambda x: x[1])
            print(f"  Best RSSI: {best_rssi_row.get('PropagationModel')} "
                  f"({best_rssi_row.get('PathLossExp', 'N/A')}) = {best_rssi_val:.2f}dBm")
        else:
            print(f"  Best RSSI: No valid RSSI measurements")

def print_init_conditions(config_name: str, config_data: Dict[str, Any]) -> None:
    """Print initialization conditions for each configuration."""
    print(f"\n=== INITIALIZATION CONDITIONS: {config_name} ===")
    print("-" * 60)
    
    core_params = [
        ("Number of Nodes", "Nodes", ""),
        ("Simulation Time", "SimTime_min", "min"),
        ("Send Interval", "Interval_s", "s"),
        ("Propagation Model", "PropagationModel", ""),
        ("Path Loss Exponent", "PathLossExp", ""),
    ]
    
    for label, key, unit in core_params:
        val = config_data.get(key, "NOT FOUND")
        unit_str = f" {unit}" if unit and val != "NOT FOUND" else ""
        print(f"{label:<25}: {val}{unit_str}")
    
    print("-" * 30)
    
    radio_params = [
        ("Initial SF", "Initial SF", ""),
        ("Initial TP", "Initial TP (dBm)", "dBm"),
        ("Path Loss Sigma", "Sigma_dB", "dB"),
    ]
    
    for label, key, unit in radio_params:
        val = config_data.get(key, "NOT FOUND")
        unit_str = f" {unit}" if unit and val != "NOT FOUND" else ""
        print(f"{label:<25}: {val}{unit_str}")
    
    print("=" * 60)

# =============================================================================
# ENHANCED Main function with validation
# =============================================================================
def main():
    ap = argparse.ArgumentParser(description="Analyze OMNeT++/FLoRa Scenario 07 (Propagation Models) - FIXED VERSION")
    ap.add_argument("--json-dir", type=Path, default=Path("json_exports"),
                    help="Directory with exported JSON files")
    ap.add_argument("--dump-keys", type=Path, default=None,
                    help="Save used keys to this JSON file")
    ap.add_argument("--validate", action="store_true",
                    help="Run additional validation checks")
    args = ap.parse_args()
    
    if not args.json_dir.exists():
        print(f"JSON directory not found: {args.json_dir}")
        print_used_keys()
        if args.dump_keys: dump_used_keys(args.dump_keys)
        return
    
    print(f"FIXED VERSION: Searching for scenario-07 files in: {args.json_dir}")
    bundles = find_all_bundles_s07_fixed(args.json_dir)
    if not bundles:
        print("No Scenario-07 bundles found (looked for 'scenario-07' + propagation models).")
        print_used_keys()
        if args.dump_keys: dump_used_keys(args.dump_keys)
        return
    
    print(f"\nFound {len(bundles)} valid configurations:")
    for i, (label, bundle) in enumerate(bundles, 1):
        print(f"{i:2d}. {label}")
    
    results: List[Dict[str, Any]] = []
    for label, bundle in bundles:
        config_data = analyze_config(bundle, label)
        print_init_conditions(label, config_data)
        results.append(config_data)
    
    if not results:
        print("No valid results to analyze.")
        print_used_keys()
        if args.dump_keys: dump_used_keys(args.dump_keys)
        return
    
    # VALIDATION: Check if all results are identical (which would indicate the bug persists)
    if args.validate or len(results) > 1:
        print(f"\n=== VALIDATION CHECK ===")
        first_result = results[0]
        identical_count = 0
        
        for i, result in enumerate(results[1:], 1):
            identical = True
            for key in ["PDR(%)", "AvgRSSI(dBm)", "Sent", "Received"]:
                if result.get(key) != first_result.get(key):
                    identical = False
                    break
            
            if identical:
                identical_count += 1
                print(f"  WARNING: Result {i+1} is identical to result 1")
            else:
                print(f"  OK: Result {i+1} differs from result 1")
        
        if identical_count == len(results) - 1:
            print(f"  ❌ CRITICAL: All {len(results)} results are identical!")
            print(f"     This suggests the bug persists - check file discovery logic")
        else:
            print(f"  ✅ GOOD: Found {len(results) - identical_count} unique results")
    
    # Print results
    print_propagation_scoreboard(results)
    print_parameter_comparison(results)  # ← Add this line
    print_detailed_analysis(results)
    
    # Keys used
    print_used_keys()
    if args.dump_keys: dump_used_keys(args.dump_keys)

if __name__ == "__main__":
    main()