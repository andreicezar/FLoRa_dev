#!/usr/bin/env python3
# Scenario-02 Analyzer (ADR ON vs ADR OFF) for OMNeT++/FLoRa
# - Uses all four JSONs: parameters, scalars, histograms/statistics, app_vectors/vectors
# - Prints context + ADR ON vs OFF scoreboard
# - Tracks and prints exact keys used; optional --dump-keys to save them
# - NEW: Prints initialization conditions from JSON parameters
# - Plain ASCII output (no emojis)
# - UPDATED: Added --area filtering support

from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Iterable
import argparse, json, re, math

# =============================================================================
# Key tracking
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
    if USED_KEYS["parameters"]:
        print("Parameters:")
        for k in sorted(USED_KEYS["parameters"]): print(f"  - {k}")
    else: print("Parameters: (none)")
    if USED_KEYS["scalars"]:
        print("Scalars:")
        for k in sorted(USED_KEYS["scalars"]): print(f"  - {k}")
    else: print("Scalars: (none)")
    if USED_KEYS["histograms"]:
        print("Histograms:")
        for k in sorted(USED_KEYS["histograms"]): print(f"  - {k}")
    else: print("Histograms: (none)")
    if USED_KEYS["vectors"]:
        print("Vectors:")
        for k in sorted(USED_KEYS["vectors"]): print(f"  - {k}")
    else: print("Vectors: (none)")

def dump_used_keys(path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "parameters": sorted(USED_KEYS["parameters"]),
                "scalars": sorted(USED_KEYS["scalars"]),
                "histograms": sorted(USED_KEYS["histograms"]),
                "vectors": sorted(USED_KEYS["vectors"]),
            },
            f, ensure_ascii=False, indent=2
        )
    print(f"[keys] Saved to: {path}")

# =============================================================================
# Area filtering helpers (same as scenario 08)
# =============================================================================
def _area_aliases(area: str) -> set[str]:
    """Allow '1x1km' and its '1km' alias (common in your file names)."""
    a = area.lower().strip().strip("_- ")
    aliases = {a}
    if "x" in a and a.endswith("km"):
        first = a.split("x", 1)[0]  # '1x1km' -> '1'
        aliases.add(f"{first}km")   # accept '_1km' too
    return aliases

def name_matches_area(filename: str, area: str | None) -> bool:
    """True if filename matches requested area (or no area requested)."""
    if not area:
        return True
    n = filename.lower()
    for alias in _area_aliases(area):
        if f"_{alias}" in n:       # we require the explicit suffix pattern
            return True
    return False

# =============================================================================
# JSON helpers
# =============================================================================
def read_json(path: Path) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in file: {path}")
        print(f"  JSON Error: {e}")
        print(f"  Line {e.lineno}, Column {e.colno}")
        print(f"  Skipping this file...")
        return {}
    except Exception as e:
        print(f"ERROR: Could not read file: {path}")
        print(f"  Error: {e}")
        print(f"  Skipping this file...")
        return {}

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
    if isinstance(obj, dict):  # top-level arrays
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
# Parsing helpers
# =============================================================================
_TIME_RX = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([a-zA-Z]+)?\s*$")
def parse_time_to_seconds(s: str) -> Optional[float]:
    if s is None: return None
    if isinstance(s, (int, float)): return float(s)
    m = _TIME_RX.match(str(s));  val = float(m.group(1)) if m else None
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
    m = _NUM_RX.search(str(s));  return float(m.group(0)) if m else None

def parse_bool_text(s: str) -> Optional[bool]:
    if isinstance(s, bool): return s
    if s is None: return None
    t = str(s).strip().lower()
    if t in ("true", "yes", "1", "on"): return True
    if t in ("false", "no", "0", "off"): return False
    return None

# =============================================================================
# File discovery (updated to support area filtering)
# =============================================================================
def find_bundle(json_dir: Path, patterns: List[str], area: str | None = None) -> Dict[str, Path]:
    pats = [p.lower() for p in patterns]
    out: Dict[str, Path] = {}
    for p in json_dir.glob("*.json"):
        name = p.name.lower()
        if not name_matches_area(p.name, area):
            continue
        if all(sub in name for sub in pats):
            if "parameters" in name and "parameters" not in out: out["parameters"] = p
            elif "scalars" in name and "scalars" not in out: out["scalars"] = p
            elif ("histograms" in name or "statistics" in name) and "histograms" not in out: out["histograms"] = p
            elif "app_vectors" in name and "app_vectors" not in out: out["app_vectors"] = p
            elif "vectors" in name and "app_vectors" not in out: out["app_vectors"] = p
    return out

# =============================================================================
# NEW: Extract initialization conditions
# =============================================================================
def extract_init_conditions(params: List[dict], scalars: List[dict]) -> Dict[str, Any]:
    """Extract initialization conditions from OMNeT++ JSON parameters"""
    init_conditions = {}
    
    # Number of nodes
    v = find_param_by_alias(params, PARAM_RX["nodes"])
    if v is not None:
        init_conditions["numberOfNodes"] = int(parse_float_from_text(v) or 0)
    
    # Initial SF
    v = find_param_by_alias(params, PARAM_RX["initial_sf"])
    if v is not None:
        n = parse_float_from_text(v)
        if n is not None:
            init_conditions["initialLoRaSF"] = int(n)
    
    # Initial TP
    v = find_param_by_alias(params, PARAM_RX["initial_tp"])
    if v is not None:
        n = parse_float_from_text(v)
        if n is not None:
            init_conditions["initialLoRaTP_dBm"] = float(n)
    
    # Send interval
    v = find_param_by_alias(params, PARAM_RX["send_interval"])
    if v is not None:
        iv = parse_time_to_seconds(v)
        if iv is not None:
            init_conditions["sendInterval_s"] = float(iv)
    
    # ADR enabled
    v = find_param_by_alias(params, PARAM_RX["adr_enabled"])
    if v is not None:
        b = parse_bool_text(v)
        if b is not None:
            init_conditions["evaluateADRinServer"] = bool(b)
    
    # Simulation time from scalars
    st = pick_scalar_by_alias(scalars, SCALAR_RX["sim_time"])
    if st is not None:
        init_conditions["simTime_s"] = float(st)
        init_conditions["simTime_min"] = float(st) / 60.0
    
    # Max transmission duration
    v = find_param_by_alias(params, PARAM_RX["max_tx_dur"])
    if v is not None:
        sec = parse_time_to_seconds(v)
        if sec is not None:
            init_conditions["maxTransmissionDuration_s"] = float(sec)
    
    # Radio parameters
    v = find_param_by_alias(params, PARAM_RX["bandwidth"])
    if v is not None:
        bw_hz = parse_bandwidth_to_hz(v)
        if bw_hz is not None:
            init_conditions["bandwidth_Hz"] = float(bw_hz)
    
    v = find_param_by_alias(params, PARAM_RX["coding_rate"])
    if v is not None:
        init_conditions["codingRate"] = v  # Just store the raw value without conversion
    
    # Look for sigma (path loss parameter)
    for p in params:
        nm = str(p.get("name", ""))
        if "sigma" in nm.lower():
            val = parse_float_from_text(p.get("value", ""))
            if val is not None:
                init_conditions["pathLoss_sigma_dB"] = float(val)
                _used_param(nm)
                break
    
    return init_conditions

def print_init_conditions(config_name: str, init_conditions: Dict[str, Any]) -> None:
    """Print initialization conditions in a formatted table"""
    print(f"\n=== INITIALIZATION CONDITIONS: {config_name} ===")
    print("-" * 60)
    
    # Core simulation parameters
    core_params = [
        ("Number of Nodes", "numberOfNodes", ""),
        ("Simulation Time", "simTime_min", "min"),
        ("Send Interval", "sendInterval_s", "s"),
        ("ADR Enabled", "evaluateADRinServer", ""),
    ]
    
    for label, key, unit in core_params:
        val = init_conditions.get(key, "NOT FOUND")
        unit_str = f" {unit}" if unit and val != "NOT FOUND" else ""
        print(f"{label:<25}: {val}{unit_str}")
    
    print("-" * 30)
    
    # Radio parameters
    radio_params = [
        ("Initial SF", "initialLoRaSF", ""),
        ("Initial TP", "initialLoRaTP_dBm", "dBm"),
        ("Bandwidth", "bandwidth_Hz", "Hz"),
        ("Coding Rate", "codingRate", ""),  # Changed to use raw value
        ("Max TX Duration", "maxTransmissionDuration_s", "s"),
        ("Path Loss Sigma", "pathLoss_sigma_dB", "dB"),
    ]
    
    for label, key, unit in radio_params:
        val = init_conditions.get(key, "NOT FOUND")
        unit_str = f" {unit}" if unit and val != "NOT FOUND" else ""
        print(f"{label:<25}: {val}{unit_str}")
    
    # Calculate expected packets per device
    if "simTime_s" in init_conditions and "sendInterval_s" in init_conditions:
        expected_packets = int(init_conditions["simTime_s"] / init_conditions["sendInterval_s"])
        print(f"{'Expected pkts/device':<25}: {expected_packets}")
    
    print("=" * 60)

# =============================================================================
# Aliases and module selectors
# =============================================================================
PARAM_RX = {
    "nodes":         [re.compile(r"\bnumberOfNodes\b", re.I)],
    "send_interval": [re.compile(r"\btimeToNextPacket\b", re.I), re.compile(r"\bsendInterval\b", re.I)],
    "adr_enabled":   [re.compile(r"\bevaluateADRinServer\b", re.I)],
    "initial_sf":    [re.compile(r"\binitialLoRaSF\b", re.I)],
    "initial_tp":    [re.compile(r"\binitialLoRaTP\b", re.I)],
    "max_tx_dur":    [re.compile(r"\bmaxTransmissionDuration\b", re.I)],
    # payload and radio params for ToA estimate
    "payload_len":   [re.compile(r"\b(appPacketLength|payloadLength|payloadBytes|packetLength|loraPayloadBytes)\b", re.I)],
    "bandwidth":     [re.compile(r"\b(bandwidth|loRaBandwidth|radioBandwidth)\b", re.I)],
    "coding_rate":   [re.compile(r"\b(initialLoRaCR)\b", re.I)],
    "preamble_syms": [re.compile(r"\b(preambleSymbols|preambleLength|preambleLen)\b", re.I)],
    "hdr_enabled":   [re.compile(r"\b(implicitHeader|header)\b", re.I)],
    "crc_enabled":   [re.compile(r"\bcrc\b", re.I)],
}

SCALAR_RX = {
    "total_received":[re.compile(r"\btotalReceivedPackets\b", re.I),
                      re.compile(r"\bLoRa_ServerPacketReceived:count\b", re.I)],
    "sent_primary":  [re.compile(r"^sentPackets$", re.I),
                      re.compile(r"^packetsSent$", re.I),
                      re.compile(r"^uplinksSent$", re.I),
                      re.compile(r"^totalSentPackets$", re.I),
                      re.compile(r"^numSent$", re.I)],
    "sent_fallback": [re.compile(r"^LoRa_AppPacketSent:count$", re.I)],
    "collisions":    [re.compile(r"\bnumCollisions\b", re.I), re.compile(r"\bcollisions\b", re.I)],
    "gw_rx_started": [re.compile(r"\bLoRaGWRadioReceptionStarted:count\b", re.I),
                      re.compile(r"\brx[_\s-]*started\b", re.I)],
    "gw_rx_ok":      [re.compile(r"\bLoRaGWRadioReceptionFinishedCorrect:count\b", re.I),
                      re.compile(r"\brx[_\s-]*ok\b", re.I)],
    "sim_time":      [re.compile(r"\bsimulated time\b", re.I)],
    "sf_bucket":     [re.compile(r"\bcounterUniqueReceivedPacketsPerSF\s*SF(\d+)\b", re.I),
                      re.compile(r"\bDER\s*SF\s*(\d+)\b", re.I)],
    "adr_cmds_recv": [re.compile(r"\breceivedADRCommands\b", re.I)],
    "adr_cmds_sent": [re.compile(r"\bSend ADR for node\b", re.I)],
    "final_sf":      [re.compile(r"\bfinalSF\b", re.I)],
    "final_tp":      [re.compile(r"\bfinalTP\b", re.I)],
    "max_tx_dur":    [re.compile(r"\bmaxTransmissionDuration\b", re.I)],
}

HIST_RX = {
    "rssi": [re.compile(r"\breceivedRSSI\b", re.I), re.compile(r"\bRSSI\b", re.I)],
    "snr":  [re.compile(r"\bminSnir\b", re.I), re.compile(r"\bSNIR\b", re.I), re.compile(r"\bSNR\b", re.I)],
    "payload_len": [re.compile(r"\bincomingPacketLengths\b", re.I),
                    re.compile(r"\b(packetLength|payloadLength)\b", re.I)],
}

VEC_RX = {
    "snr":  [re.compile(r"\bVector of SNIR per node\b", re.I), re.compile(r"\bSNIR\b", re.I), re.compile(r"\bSNR\b", re.I)],
    "rssi": [re.compile(r"\bVector of RSSI per node\b", re.I), re.compile(r"\bRSSI\b", re.I)],
}

SERVER_MOD = re.compile(r"LoRaNetworkTest\.networkServer\.app\[0\]", re.I)
GW_MOD     = re.compile(r"(LoRaGW|gateway|GWNic|GW\[\d+\])", re.I)
NODE_APP_MOD_RX = re.compile(r".*\.loRaNodes\[\d+\]\.app\[0\]$", re.I)
NODE_INDEX_RX   = re.compile(r"\bloRaNodes\[(\d+)\]\b", re.I)
TRANSMITTER_MOD_RX = re.compile(r"\.loRaNic\.radio\.transmitter$", re.I)

AIRTIME_NAMES = [
    re.compile(r"air[_\s-]*time", re.I),
    re.compile(r"time[_\s-]*on[_\s-]*air", re.I),
    re.compile(r"\btoa\b", re.I),
    re.compile(r"tx[_\s-]*duration", re.I),
    re.compile(r"tx[_\s-]*time", re.I),
]

# =============================================================================
# Lookups and metric helpers
# =============================================================================
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
            nm  = str(s.get("name","")); mod = str(s.get("module",""))
            if module_rx is not None and not module_rx.search(mod): continue
            if rx.search(nm) and s.get("value") is not None:
                _used_scalar(nm)
                try: return float(s["value"])
                except Exception:
                    v = parse_float_from_text(s["value"])
                    if v is not None: return float(v)
    return None

def sf_counts_from_scalars(scalars: Iterable[Dict[str, Any]]) -> Dict[int,int]:
    counts: Dict[int,int] = {}
    for s in scalars:
        nm = str(s.get("name",""))
        m1 = re.search(r"\bcounterUniqueReceivedPacketsPerSF\s*SF(\d+)\b", nm, re.I)
        m2 = re.search(r"\bDER\s*SF\s*(\d+)\b", nm, re.I)
        m = m1 or m2
        if not m: continue
        try: sf = int(m.group(1))
        except Exception: continue
        try: val = int(float(s.get("value", 0)))
        except Exception:
            v = parse_float_from_text(s.get("value"));  val = int(v) if v is not None else None
        if val is None: continue
        counts[sf] = counts.get(sf, 0) + val
        _used_scalar(nm)
    return counts

# ---- Histogram & vector stats ----
def _hist_stat(entry: dict, field: str) -> Optional[float]:
    stat = entry.get("stat")
    if isinstance(stat, dict) and field in stat:
        try: return float(stat[field])
        except Exception: return None
    return None

def hist_stat_count(histograms: List[dict], name_rxs: List[re.Pattern]) -> int:
    total_cnt = 0
    for h in histograms:
        nm = (h.get("name","") or "")
        if not any(rx.search(nm) for rx in name_rxs): continue
        cnt = _hist_stat(h, "count")
        if isinstance(cnt, (int, float)):
            total_cnt += int(cnt); _used_hist(nm)
    return total_cnt

def hist_stat_sum(histograms: List[dict], name_rxs: List[re.Pattern]) -> Optional[float]:
    total = 0.0; used = False
    for h in histograms:
        nm = (h.get("name","") or "")
        if not any(rx.search(nm) for rx in name_rxs): continue
        s = _hist_stat(h, "sum")
        if s is not None:
            used = True; total += s; _used_hist(nm)
    return total if used else None

def hist_stat_mean(histograms: List[dict], name_rxs: List[re.Pattern]) -> Optional[float]:
    total_sum = 0.0; total_cnt = 0.0; used = False
    for h in histograms:
        nm = (h.get("name","") or "")
        if not any(rx.search(nm) for rx in name_rxs): continue
        cnt = _hist_stat(h, "count"); sm = _hist_stat(h, "sum")
        if cnt and sm is not None and cnt > 0:
            total_cnt += cnt; total_sum += sm; used = True; _used_hist(nm)
    return (total_sum/total_cnt) if used and total_cnt>0 else None

def hist_stat_median(histograms: List[dict], name_rxs: List[re.Pattern]) -> Optional[float]:
    for h in histograms:
        nm = (h.get("name","") or "")
        if not any(rx.search(nm) for rx in name_rxs): continue
        med = _hist_stat(h, "median")
        if med is not None:
            _used_hist(nm); return med
    # fallback via bins (approx)
    values: List[float] = []
    for h in histograms:
        nm = (h.get("name","") or "")
        if not any(rx.search(nm) for rx in name_rxs): continue
        bins = h.get("bins")
        if isinstance(bins, list):
            for b in bins:
                if isinstance(b, dict) and "count" in b:
                    c  = int(float(b["count"]))
                    lo = float(b.get("lower", 0.0)); up = float(b.get("upper", lo))
                    values.extend([0.5*(lo+up)] * c)
            _used_hist(nm)
    if values:
        values.sort(); n = len(values); mid = n//2
        return values[mid] if n % 2 else 0.5*(values[mid-1]+values[mid])
    return None

def _vec_series_values(entry: dict) -> Optional[List[float]]:
    # A) direct 1D arrays
    for valkey in ("y", "values_y", "vecvalue", "value", "values", "data", "v"):
        arr = entry.get(valkey)
        if isinstance(arr, list) and arr and all(not isinstance(x, (list, tuple, dict)) for x in arr):
            out = []
            for x in arr:
                try: out.append(float(x))
                except Exception: pass
            if out: return out
    # B) separate time/value arrays
    for tkey, vkey in (("time","value"),("t","v"),("vectime","vecvalue"),("x","y")):
        varr = entry.get(vkey)
        if isinstance(varr, list) and varr:
            out = []
            for x in varr:
                try: out.append(float(x))
                except Exception: pass
            if out: return out
    # C) paired samples in "values": [[t,v], ...] or dicts
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

def vector_stats(vectors: List[dict], name_rxs: List[re.Pattern]) -> Tuple[Optional[float], Optional[float], int]:
    vals: List[float] = []
    for v in vectors:
        nm = (v.get("name","") or "")
        if not any(rx.search(nm) for rx in name_rxs): continue
        series = _vec_series_values(v)
        if series:
            vals.extend(series); _used_vector(nm)
    if not vals: return None, None, 0
    vals.sort(); n = len(vals); mid = n//2
    mean = sum(vals)/n
    median = vals[mid] if n%2==1 else 0.5*(vals[mid-1]+vals[mid])
    return mean, median, n

# ---- Sent/received/collisions and GW RX ----
PRIMARY_SENT_NAMES = SCALAR_RX["sent_primary"]
FALLBACK_SENT_NAME = SCALAR_RX["sent_fallback"][0]  # regex object

def sum_sent_packets_unique(scalars: List[dict]) -> int:
    per_module: Dict[str, Dict[str, Any]] = {}
    for s in scalars:
        mod = s.get("module",""); nm = s.get("name",""); v = s.get("value", None)
        if v is None or not NODE_APP_MOD_RX.fullmatch(mod or ""): continue
        slot = "primary" if any(rx.fullmatch(nm or "") for rx in PRIMARY_SENT_NAMES) else ("secondary" if FALLBACK_SENT_NAME.fullmatch(nm or "") else None)
        if not slot: continue
        d = per_module.setdefault(mod, {})
        if slot == "primary" and "primary" not in d:
            d["primary"] = float(v); d["primary_name"] = nm
        elif slot == "secondary" and "primary" not in d and "secondary" not in d:
            d["secondary"] = float(v); d["secondary_name"] = nm
    total = 0.0
    for d in per_module.values():
        if "primary" in d: total += d["primary"]; _used_scalar(d.get("primary_name",""))
        elif "secondary" in d: total += d["secondary"]; _used_scalar(d.get("secondary_name",""))
    return int(total)

def pick_total_received(scalars: List[dict]) -> Optional[int]:
    v = pick_scalar_by_alias(scalars, SCALAR_RX["total_received"], module_rx=SERVER_MOD)
    if v is None: v = pick_scalar_by_alias(scalars, SCALAR_RX["total_received"], module_rx=None)
    return int(v) if v is not None else None

def pick_collisions(scalars: List[dict]) -> Optional[int]:
    v = pick_scalar_by_alias(scalars, SCALAR_RX["collisions"], module_rx=GW_MOD)
    if v is None: v = pick_scalar_by_alias(scalars, SCALAR_RX["collisions"], module_rx=None)
    return int(v) if v is not None else None

def pick_gw_rx_metrics(scalars: List[dict], histograms: List[dict], vectors: List[dict]) -> Tuple[Optional[int], Optional[int]]:
    started = pick_scalar_by_alias(scalars, SCALAR_RX["gw_rx_started"], module_rx=GW_MOD)
    ok      = pick_scalar_by_alias(scalars, SCALAR_RX["gw_rx_ok"],      module_rx=GW_MOD)
    if started is not None or ok is not None:
        return (int(started) if started is not None else None, int(ok) if ok is not None else None)
    # fallback via hist sums
    ssum = hist_stat_sum(histograms, [re.compile(r"rx[_\s-]*started", re.I)])
    osum = hist_stat_sum(histograms, [re.compile(r"rx[_\s-]*ok", re.I)])
    if ssum is not None or osum is not None:
        return (int(ssum) if ssum is not None else None, int(osum) if osum is not None else None)
    # final fallback via vectors length
    def vec_len_match(name_rx: re.Pattern) -> Optional[int]:
        for v in vectors:
            nm = (v.get("name","") or "")
            if name_rx.search(nm):
                series = _vec_series_values(v)
                if series is not None:
                    _used_vector(nm); return len(series)
        return None
    svec = vec_len_match(re.compile(r"rx[_\s-]*started", re.I))
    ovec = vec_len_match(re.compile(r"rx[_\s-]*ok", re.I))
    return (svec, ovec)

def pick_total_airtime_seconds(scalars: List[dict], histograms: List[dict]) -> Optional[float]:
    s = hist_stat_sum(histograms, AIRTIME_NAMES)
    if s is not None: return float(s)
    total = 0.0; found = False
    for sc in scalars:
        nm = (sc.get("name","") or "")
        if not any(rx.search(nm) for rx in AIRTIME_NAMES): continue
        v = sc.get("value", None)
        if v is None: continue
        try: total += float(v); found = True; _used_scalar(nm)
        except Exception:
            fv = parse_float_from_text(v)
            if fv is not None: total += fv; found = True; _used_scalar(nm)
    return total if found else None

# ---- ADR Commands ----
def pick_adr_commands(scalars: List[dict]) -> Tuple[Optional[int], Optional[int]]:
    """
    Returns (ADR commands received by EDs, ADR commands sent by NS)
    """
    # Commands received by end devices - sum across all nodes
    adr_recv_total = 0
    adr_recv_found = False
    for s in scalars:
        nm = str(s.get("name", ""))
        mod = str(s.get("module", ""))
        if re.search(r"\breceivedADRCommands\b", nm, re.I):
            if NODE_APP_MOD_RX.search(mod) or not mod:  # prefer node modules but allow any
                try:
                    val = float(s.get("value", 0))
                    adr_recv_total += int(val)
                    adr_recv_found = True
                    _used_scalar(nm)
                except Exception:
                    pass
    
    # Commands sent by network server - sum all "Send ADR for node" entries
    adr_sent_total = 0
    adr_sent_found = False
    for s in scalars:
        nm = str(s.get("name", ""))
        mod = str(s.get("module", ""))
        if re.search(r"\bSend ADR for node\b", nm, re.I):
            if SERVER_MOD.search(mod) or not mod:  # prefer server modules but allow any
                try:
                    val = float(s.get("value", 0))
                    adr_sent_total += int(val)
                    adr_sent_found = True
                    _used_scalar(nm)
                except Exception:
                    pass
    
    return (adr_recv_total if adr_recv_found else None, 
            adr_sent_total if adr_sent_found else None)

# ---- ToA estimation fallbacks ----
def extract_node_index(mod: str) -> Optional[int]:
    m = NODE_INDEX_RX.search(mod or "")
    if not m: return None
    try: return int(m.group(1))
    except Exception: return None

def sent_packets_by_node(scalars: List[dict]) -> Dict[int, int]:
    by_node: Dict[int, Dict[str, float]] = {}
    for s in scalars:
        mod = s.get("module", "") or ""
        nm  = s.get("name", "") or ""
        v   = s.get("value", None)
        if v is None or not NODE_APP_MOD_RX.fullmatch(mod):
            continue

        node = extract_node_index(mod)
        if node is None:
            continue

        slot = "primary" if any(rx.fullmatch(nm) for rx in PRIMARY_SENT_NAMES) \
               else ("secondary" if FALLBACK_SENT_NAME.fullmatch(nm) else None)
        if not slot:
            continue

        try:
            val = float(v)
        except Exception:
            fv = parse_float_from_text(v)
            val = float(fv) if fv is not None else None
        if val is None:
            continue

        d = by_node.setdefault(node, {})
        if slot == "primary" and "primary" not in d:
            d["primary"] = val
            d["primary_name"] = nm
            _used_scalar(nm)
        elif slot == "secondary" and "primary" not in d and "secondary" not in d:
            d["secondary"] = val
            d["secondary_name"] = nm
            _used_scalar(nm)

    out: Dict[int, int] = {}
    for node, d in by_node.items():
        if "primary" in d:
            out[node] = int(d["primary"])
        elif "secondary" in d:
            out[node] = int(d["secondary"])
    return out


def preamble_seconds_by_node(scalars: List[dict]) -> Dict[int, float]:
    out: Dict[int, float] = {}
    for s in scalars:
        mod = s.get("module", "") or ""
        nm  = s.get("name", "") or ""
        if not re.search(r"\bpreambleDuration\b", nm, re.I):
            continue
        if not TRANSMITTER_MOD_RX.search(mod):
            continue

        node = extract_node_index(mod)
        if node is None:
            continue

        val = s.get("value", None)
        sec = parse_time_to_seconds(val) if val is not None else None
        if sec is None:
            try:
                sec = float(val)
            except Exception:
                sec = parse_float_from_text(val)
        if sec is None:
            continue

        out[node] = float(sec)
        _used_scalar(nm)
    return out


def toa_from_preamble_only(scalars: List[dict]) -> Optional[float]:
    sent = sent_packets_by_node(scalars);  pre = preamble_seconds_by_node(scalars)
    if not sent or not pre: return None
    total = 0.0
    for node, cnt in sent.items():
        if node in pre: total += cnt * pre[node]
    return total if total > 0 else None

def parse_bandwidth_to_hz(s: str) -> Optional[float]:
    if s is None: return None
    if isinstance(s, (int, float)): return float(s)
    t = str(s).strip().lower().replace(" ", "")
    m = re.match(r"^([0-9]*\.?[0-9]+)(m?g?k?)hz?$", t)
    if m:
        val = float(m.group(1)); suf = m.group(2)
        if suf == "g" or suf == "ghz": return val * 1e9
        if suf == "m" or suf == "mhz": return val * 1e6
        if suf == "k" or suf == "khz": return val * 1e3
        return val
    try: return float(t)
    except Exception: return None

def lora_toa_seconds(payload_bytes: int, sf: int, bw_hz: float, cr: int,
                     preamble_syms: int=8, header_enabled: bool=True, crc_enabled: bool=True) -> float:
    Tsym = (2.0 ** int(sf)) / float(bw_hz)
    IH = 0 if header_enabled else 1
    CRC = 1 if crc_enabled else 0
    DE = 1 if (int(sf) >= 11 and float(bw_hz) <= 125000.0) else 0
    num = (8*int(payload_bytes) - 4*int(sf) + 28 + 16*CRC - 20*IH)
    den = (4 * (int(sf) - 2*DE))
    tmp = max(0.0, (num / den))
    payloadSymbNb = 8 + math.ceil(tmp) * (int(cr) + 4)
    Tpreamble = (int(preamble_syms) + 4.25) * Tsym
    Tpayload  = payloadSymbNb * Tsym
    return Tpreamble + Tpayload

def mean_payload_from_hist(histograms: List[dict]) -> Optional[float]:
    m = hist_stat_mean(histograms, HIST_RX["payload_len"])
    return float(m) if m is not None else None

def payload_bytes_estimate(params: List[dict], histograms: List[dict]) -> Optional[int]:
    m = mean_payload_from_hist(histograms)
    if m is not None:
        _used_hist("payloadLength(histo)");  return int(round(m))
    v = find_param_by_alias(params, PARAM_RX["payload_len"])
    if v is not None:
        n = parse_float_from_text(v)
        if n is not None: return int(round(n))
    return None

def estimate_sf(params: List[dict], scalars: List[dict]) -> int:
    v = pick_scalar_by_alias(scalars, SCALAR_RX.get("final_sf", []))
    if isinstance(v, (int, float)) and 7 <= int(v) <= 12: return int(v)
    v = find_param_by_alias(params, PARAM_RX["initial_sf"])
    n = parse_float_from_text(v) if v is not None else None
    if n is not None and 7 <= int(n) <= 12: return int(n)
    return 12

def estimate_radio_params(params: List[dict]) -> Tuple[float, int, int, bool, bool]:
    bw = find_param_by_alias(params, PARAM_RX["bandwidth"])
    bw_hz = parse_bandwidth_to_hz(bw) if bw is not None else 125000.0
    if bw_hz is None: bw_hz = 125000.0
    crs = find_param_by_alias(params, PARAM_RX["coding_rate"])
    cr = int(parse_float_from_text(crs) or 1)  # Just use raw value, defaults to 1
    if cr < 1 or cr > 4: cr = 1
    p = find_param_by_alias(params, PARAM_RX["preamble_syms"])
    pre = int(parse_float_from_text(p) or 8)
    hdr = find_param_by_alias(params, PARAM_RX["hdr_enabled"])
    hdr_b = parse_bool_text(hdr);  header_enabled = True if hdr_b is None else bool(hdr_b)
    crc = find_param_by_alias(params, PARAM_RX["crc_enabled"])
    crc_b = parse_bool_text(crc);  crc_enabled = True if crc_b is None else bool(crc_b)
    return float(bw_hz), int(cr), int(pre), header_enabled, crc_enabled

def compute_toa_estimate_from_phy(params: List[dict], histograms: List[dict], scalars: List[dict], total_sent: int) -> Optional[float]:
    if not total_sent: return None
    pl = payload_bytes_estimate(params, histograms)
    if pl is None: return None
    sf = estimate_sf(params, scalars)
    bw_hz, cr, pre, hdr, crc = estimate_radio_params(params)
    per_pkt = lora_toa_seconds(pl, sf, bw_hz, cr, preamble_syms=pre, header_enabled=hdr, crc_enabled=crc)
    return per_pkt * float(total_sent)

# =============================================================================
# Analyze one bundle
# =============================================================================
def analyze_config(bundle: Dict[str, Path], label: str) -> Dict[str, Any]:
    res: Dict[str, Any] = {"Configuration": label}

    # Load JSONs
    params_json     = read_json(bundle["parameters"]) if "parameters" in bundle else {}
    scalars_json    = read_json(bundle["scalars"])    if "scalars" in bundle    else {}
    histograms_json = read_json(bundle["histograms"]) if "histograms" in bundle else {}
    vectors_json    = read_json(bundle["app_vectors"])if "app_vectors" in bundle else {}

    # Extract lists
    params     = get_parameters_list(params_json)
    scalars    = get_scalars_list(scalars_json)
    histograms = get_histograms_list(histograms_json)
    vectors    = get_vectors_list(vectors_json)

    # NEW: Extract and print initialization conditions
    init_conditions = extract_init_conditions(params, scalars)
    print_init_conditions(label, init_conditions)

    # Parameters
    v = find_param_by_alias(params, PARAM_RX["nodes"])
    if v is not None: res["Nodes"] = int(parse_float_from_text(v) or 0)

    v = find_param_by_alias(params, PARAM_RX["send_interval"])
    iv = parse_time_to_seconds(v) if v is not None else None
    if iv is not None: res["Interval_s"] = float(iv)

    v = find_param_by_alias(params, PARAM_RX["adr_enabled"])
    b = parse_bool_text(v) if v is not None else None
    if b is not None: res["ADR Enabled"] = bool(b)

    v = find_param_by_alias(params, PARAM_RX["initial_sf"])
    if v is not None:
        n = parse_float_from_text(v)
        if n is not None: res["Initial SF"] = int(n)

    v = find_param_by_alias(params, PARAM_RX["initial_tp"])
    if v is not None:
        n = parse_float_from_text(v)
        if n is not None: res["Initial TP (dBm)"] = float(n)

    # Sim time and max TX duration (context)
    st = pick_scalar_by_alias(scalars, SCALAR_RX["sim_time"])
    if st is not None: res["SimTime_s"] = float(st)
    v = find_param_by_alias(params, PARAM_RX["max_tx_dur"])
    if v is None:
        mx = pick_scalar_by_alias(scalars, SCALAR_RX["max_tx_dur"])
        v = f"{mx}s" if mx is not None else None
    if v is not None:
        sec = parse_time_to_seconds(v)
        if sec is not None: res["Max TX Duration (s)"] = float(sec)

    # Totals
    total_sent = sum_sent_packets_unique(scalars)
    if total_sent == 0:
        v = pick_scalar_by_alias(scalars, SCALAR_RX["sent_primary"]) or pick_scalar_by_alias(scalars, SCALAR_RX["sent_fallback"])
        if v is not None: total_sent = int(v)
    res["Total Sent"] = int(total_sent)

    tr = pick_total_received(scalars)
    if tr is not None: res["Total Received"] = int(tr)

    if res.get("Total Sent",0) > 0 and isinstance(res.get("Total Received"), int):
        res["Overall PDR (%)"] = 100.0 * res["Total Received"] / res["Total Sent"]

    # Collisions
    coll = pick_collisions(scalars)
    if coll is not None: res["Collisions"] = int(coll)

    # GW Rx metrics
    rx_started, rx_ok = pick_gw_rx_metrics(scalars, histograms, vectors)
    if rx_started is not None: res["GW Rx Started"] = int(rx_started)
    if rx_ok is not None:      res["GW Rx OK"]      = int(rx_ok)
    if isinstance(res.get("GW Rx Started"), int) and res["GW Rx Started"]>0 and isinstance(res.get("GW Rx OK"), int):
        res["GW RxOK (%)"] = 100.0 * res["GW Rx OK"] / res["GW Rx Started"]

    # Airtime (prefer explicit; else fallbacks)
    toa = pick_total_airtime_seconds(scalars, histograms)
    if toa is None:
        toa = toa_from_preamble_only(scalars)
        if toa is not None:
            res["Total ToA (s)"] = float(toa)
            res["ToA Note"] = "preambleDuration x sentPackets (lower bound)"
        else:
            est = compute_toa_estimate_from_phy(params, histograms, scalars, res.get("Total Sent", 0))
            if est is not None and est > 0:
                res["Total ToA (s)"] = float(est)
                res["ToA Note"] = "estimated from payload,SF,BW,CR (Semtech formula)"
    else:
        res["Total ToA (s)"] = float(toa)

    # SF distribution
    sf_counts = sf_counts_from_scalars(scalars)
    if sf_counts:
        total = sum(sf_counts.values())
        mean_sf = sum(sf*c for sf,c in sf_counts.items())/total if total>0 else None
        if mean_sf is not None: res["Mean SF"] = float(mean_sf)
        s79   = sum(c for sf,c in sf_counts.items() if 7<=sf<=9)
        s1012 = sum(c for sf,c in sf_counts.items() if 10<=sf<=12)
        if total>0:
            res["SF7-9 (%)"]   = 100.0 * s79/total
            res["SF10-12 (%)"] = 100.0 * s1012/total

    # SNIR and RSSI (combine histograms and vectors)
    snr_mean_h = hist_stat_mean(histograms, HIST_RX["snr"])
    snr_med_h  = hist_stat_median(histograms, HIST_RX["snr"])
    snr_cnt_h  = hist_stat_count(histograms, HIST_RX["snr"])
    snr_mean_v, snr_med_v, snr_cnt_v = vector_stats(vectors, VEC_RX["snr"])
    if (snr_cnt_h or snr_cnt_v):
        if snr_cnt_h and snr_mean_h is not None and snr_cnt_v and snr_mean_v is not None:
            res["Mean SNIR (dB)"] = float((snr_mean_h*snr_cnt_h + snr_mean_v*snr_cnt_v) / float(snr_cnt_h + snr_cnt_v))
            res["Median SNIR (dB)"] = float(snr_med_h if snr_cnt_h >= snr_cnt_v and snr_med_h is not None
                                            else snr_med_v if snr_med_v is not None else (snr_med_h if snr_med_h is not None else snr_mean_h))
        elif snr_cnt_h and snr_mean_h is not None:
            res["Mean SNIR (dB)"] = float(snr_mean_h)
            if snr_med_h is not None: res["Median SNIR (dB)"] = float(snr_med_h)
        elif snr_cnt_v and snr_mean_v is not None:
            res["Mean SNIR (dB)"] = float(snr_mean_v)
            if snr_med_v is not None: res["Median SNIR (dB)"] = float(snr_med_v)

    rssi_mean_h = hist_stat_mean(histograms, HIST_RX["rssi"])
    rssi_med_h  = hist_stat_median(histograms, HIST_RX["rssi"])
    rssi_cnt_h  = hist_stat_count(histograms, HIST_RX["rssi"])
    rssi_mean_v, rssi_med_v, rssi_cnt_v = vector_stats(vectors, VEC_RX["rssi"])
    if (rssi_cnt_h or rssi_cnt_v):
        if rssi_cnt_h and rssi_mean_h is not None and rssi_cnt_v and rssi_mean_v is not None:
            res["Mean RSSI (dBm)"] = float((rssi_mean_h*rssi_cnt_h + rssi_mean_v*rssi_cnt_v) / float(rssi_cnt_h + rssi_cnt_v))
            res["Median RSSI (dBm)"] = float(rssi_med_h if rssi_cnt_h >= rssi_cnt_v and rssi_med_h is not None
                                             else rssi_med_v if rssi_med_v is not None else (rssi_med_h if rssi_med_h is not None else rssi_mean_h))
        elif rssi_cnt_h and rssi_mean_h is not None:
            res["Mean RSSI (dBm)"] = float(rssi_mean_h)
            if rssi_med_h is not None: res["Median RSSI (dBm)"] = float(rssi_med_h)
        elif rssi_cnt_v and rssi_mean_v is not None:
            res["Mean RSSI (dBm)"] = float(rssi_mean_v)
            if rssi_med_v is not None: res["Median RSSI (dBm)"] = float(rssi_med_v)

    # ADR commands (NEW)
    adr_recv, adr_sent = pick_adr_commands(scalars)
    if adr_recv is not None: 
        res["ADR Cmds (ED recv)"] = int(adr_recv)
        res["ADR Cmds"] = int(adr_recv)  # backward compatibility
    if adr_sent is not None: 
        res["ADR Cmds (NS sent)"] = int(adr_sent)

    return res

# =============================================================================
# Printing
# =============================================================================
def fmt_num(x, digits=2):
    return f"{x:.{digits}f}" if isinstance(x, (int,float)) else "NA"

def print_scoreboard(rows: List[Dict[str, Any]]):
    keys = [
        "Total Sent", "Total Received", "Overall PDR (%)",
        "Collisions", "GW Rx Started", "GW Rx OK", "GW RxOK (%)",
        "Total ToA (s)", "Mean SF", "SF7-9 (%)", "SF10-12 (%)",
        "Mean SNIR (dB)", "Median SNIR (dB)",
        "Mean RSSI (dBm)", "Median RSSI (dBm)",
        "ADR Cmds",
        "ADR Cmds (ED recv)",
        "ADR Cmds (NS sent)"
    ]
    labels = {
        "Total Sent":"Total Sent",
        "Total Received":"Total Received",
        "Overall PDR (%)":"PDR (%)",
        "Collisions":"Collisions",
        "GW Rx Started":"GW Rx Started",
        "GW Rx OK":"GW Rx OK",
        "GW RxOK (%)":"RxOK (%)",
        "Total ToA (s)":"Total ToA (s)",
        "Mean SF":"Mean SF",
        "SF7-9 (%)":"SF7-9 (%)",
        "SF10-12 (%)":"SF10-12 (%)",
        "Mean SNIR (dB)":"Mean SNIR (dB)",
        "Median SNIR (dB)":"Median SNIR (dB)",
        "Mean RSSI (dBm)":"Mean RSSI (dBm)",
        "Median RSSI (dBm)":"Median RSSI (dBm)",
        "ADR Cmds":"ADR Cmds",
        "ADR Cmds (ED recv)":"ADR Cmds (ED recv)",
        "ADR Cmds (NS sent)":"ADR Cmds (NS sent)",
    }

    def is_on(r): return bool(r.get("ADR Enabled", False))
    if len(rows) < 2:
        print("\n=== Scenario 02 - Scoreboard ===")
        for r in rows:
            print(f"\n[{r.get('Configuration','')}]")
            for k in keys:
                print(f"  {labels[k]:<20}: {fmt_num(r.get(k))}")
        return

    row_on  = None
    row_off = None
    for r in rows:
        if is_on(r): row_on = r
        else: row_off = r
    if row_on is None or row_off is None:
        row_on = rows[0]; row_off = rows[1]

    print("\n" + "="*120)
    print("SCENARIO 02 - ADR ON vs ADR OFF (Scoreboard)")
    print("="*120)
    print(f"{'Metric':<22} {'ADR ON':>18} {'ADR OFF':>18} {'Delta (ON-OFF)':>18}")
    print("-"*120)
    for k in keys:
        a = row_on.get(k, None); b = row_off.get(k, None); delta = None
        if isinstance(a, (int,float)) and isinstance(b, (int,float)):
            delta = a - b
        print(f"{labels[k]:<22} {fmt_num(a,3):>18} {fmt_num(b,3):>18} {fmt_num(delta,3):>18}")
    print("="*120)

# =============================================================================
# Main
# =============================================================================
def main():
    ap = argparse.ArgumentParser(description="Analyze OMNeT++/FLoRa Scenario 02 (ADR vs Fixed SF12)")
    ap.add_argument("--json-dir", type=Path, default=Path("json_exports"),
                    help="Directory with exported JSON files")
    ap.add_argument("--dump-keys", type=Path, default=None,
                    help="Save used keys to this JSON file")
    ap.add_argument("--area", type=str, default=None,
                    help="Area suffix to filter files by (e.g. 1x1km, 2x2km, 3x3km).")
    args = ap.parse_args()

    if not args.json_dir.exists():
        print(f"JSON directory not found: {args.json_dir}")
        print_used_keys()
        if args.dump_keys: dump_used_keys(args.dump_keys)
        return

    print(f"Searching for scenario files in: {args.json_dir}")
    if args.area:
        print(f"Filtering by area: {args.area}")

    adr_bundle   = find_bundle(args.json_dir, ["scenario-02", "adr-enabled"], area=args.area)
    fixed_bundle = find_bundle(args.json_dir, ["scenario-02", "fixed", "sf12"], area=args.area)

    results: List[Dict[str, Any]] = []

    if adr_bundle.get("parameters") and adr_bundle.get("scalars"):
        results.append(analyze_config(adr_bundle, "scenario-02-adr-enabled"))
    else:
        print("ADR-enabled bundle incomplete or missing")

    if fixed_bundle.get("parameters") and fixed_bundle.get("scalars"):
        results.append(analyze_config(fixed_bundle, "scenario-02-fixed-sf12"))
    else:
        print("Fixed-SF12 bundle incomplete or missing")

    if not results:
        print("No valid results to analyze.")
        print_used_keys()
        if args.dump_keys: dump_used_keys(args.dump_keys)
        return

    # Context table
    print("\n" + "="*100)
    print("SCENARIO 02 - OMNeT++ FLoRa ANALYSIS RESULTS (context)")
    print("="*100)
    header = ("Configuration","Nodes","SimTime_s","Interval_s","ADR Enabled","Initial SF","Initial TP (dBm)")
    fmt = "{:<28} {:>5} {:>10} {:>11} {:>11} {:>10} {:>17}"
    print(fmt.format(*header))
    for r in results:
        row = (
            r.get("Configuration",""),
            r.get("Nodes","NA"),
            f"{r.get('SimTime_s','NA'):.1f}" if isinstance(r.get("SimTime_s"), (int,float)) else "NA",
            f"{r.get('Interval_s','NA'):.1f}" if isinstance(r.get("Interval_s"), (int,float)) else "NA",
            str(r.get("ADR Enabled","NA")),
            r.get("Initial SF","NA"),
            f"{r.get('Initial TP (dBm)','NA'):.1f}" if isinstance(r.get("Initial TP (dBm)"), (int,float)) else "NA",
        )
        print(fmt.format(*row))
    print("="*100)

    # Scoreboard with deltas
    print_scoreboard(results)

    # Keys used
    print_used_keys()
    if args.dump_keys: dump_used_keys(args.dump_keys)

if __name__ == "__main__":
    main()