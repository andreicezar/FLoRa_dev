# Scenario-05 Analyzer (Baseline variants) for OMNeT++/FLoRa
# Area-aware version: supports --area to pick the proper *_<area> JSONs
#
# - Matches Scenario-02 script structure and printouts
# - Uses all four JSONs where present (parameters, scalars, histograms/statistics, app_vectors/vectors)
# - Prints per-config Initialization Conditions, a context table, and a multi-config scoreboard
# - Tracks and prints exact keys used; optional --dump-keys to save them
# - Plain ASCII output (no emojis)

from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Iterable
import argparse, json, re, math, statistics, sys

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
# JSON helpers
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
# File discovery (now area-aware)
# =============================================================================
def _area_token_variants(area: str) -> List[str]:
    """
    Produce a small set of filename tokens that may represent this area.
    E.g. '1x1km' -> ['_1x1km', '-1x1km', '_1km', '-1km']
         '1km'   -> ['_1km',   '-1km',   '_1x1km', '-1x1km']  (be liberal)
    """
    a = area.strip().lower()
    toks = set()
    for sep in ("_", "-"):
        toks.add(f"{sep}{a}")
        if "x" in a and a.endswith("km"):
            # also accept the short form (e.g. 1x1km -> 1km)
            short = a.split("x")[0] + "km"
            toks.add(f"{sep}{short}")
        if "x" not in a and a.endswith("km"):
            # also accept long form (e.g. 1km -> 1x1km)
            try:
                n = re.match(r"^(\d+)km$", a)
                if n:
                    longf = f"{n.group(1)}x{n.group(1)}km"
                    toks.add(f"{sep}{longf}")
            except Exception:
                pass
    return sorted(toks)

def _name_has_area_tag(name: str, area_tokens: List[str]) -> bool:
    low = name.lower()
    return any(tok in low for tok in area_tokens)

def find_bundle(json_dir: Path, base_tokens: List[str], area_tokens: Optional[List[str]]) -> Dict[str, Path]:
    pats = [p.lower() for p in base_tokens]
    out: Dict[str, Path] = {}
    for p in json_dir.glob("*.json"):
        name = p.name.lower()
        if all(sub in name for sub in pats):
            if area_tokens and not _name_has_area_tag(name, area_tokens):
                continue
            if "parameters" in name and "parameters" not in out: out["parameters"] = p
            elif "scalars" in name and "scalars" not in out: out["scalars"] = p
            elif ("histograms" in name or "statistics" in name) and "histograms" not in out: out["histograms"] = p
            elif "app_vectors" in name and "app_vectors" not in out: out["app_vectors"] = p
            elif "vectors" in name and "app_vectors" not in out: out["app_vectors"] = p
    return out

def find_all_bundles_s05(json_dir: Path, area: Optional[str]) -> List[Tuple[str, Dict[str, Path]]]:
    """
    Finds every sub-scenario for scenario-05-baseline-* (with -s#) and returns (label, bundle) pairs.
    If --area is given, restrict to files that contain that area tag (supports '_1x1km' and '_1km' styles).
    """
    area_tokens = _area_token_variants(area) if area else None

    bases = set()
    for p in json_dir.glob("*.json"):
        low = p.name.lower()
        if "scenario-05" in low and "baseline" in low and re.search(r"-s\d+", low):
            if area_tokens and not _name_has_area_tag(low, area_tokens):
                continue
            base = re.sub(r"_(parameters|scalars|histograms|statistics|app_vectors|vectors|extracted)\.json$",
                          "", p.name, flags=re.I)
            bases.add(base)

    out: List[Tuple[str, Dict[str, Path]]] = []
    for base in sorted(bases):
        label = base
        toks = [part for part in base.lower().split("-") if part]
        bundle = find_bundle(json_dir, toks, area_tokens)
        if bundle.get("parameters") and bundle.get("scalars"):
            out.append((label, bundle))
    return out

# =============================================================================
# Aliases and module selectors (unchanged)
# =============================================================================
PARAM_RX = {
    "nodes":         [re.compile(r"\bnumberOfNodes\b", re.I)],
    "send_interval": [re.compile(r"\btimeToNextPacket\b", re.I), re.compile(r"\bsendInterval\b", re.I)],
    "adr_enabled":   [re.compile(r"\bevaluateADRinServer\b", re.I)],
    "initial_sf":    [re.compile(r"\binitialLoRaSF\b", re.I)],
    "initial_tp":    [re.compile(r"\binitialLoRaTP\b", re.I)],
    "max_tx_dur":    [re.compile(r"\bmaxTransmissionDuration\b", re.I)],
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
# Lookups and metric helpers (unchanged)
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
    for valkey in ("y", "values_y", "vecvalue", "value", "values", "data", "v"):
        arr = entry.get(valkey)
        if isinstance(arr, list) and arr and all(not isinstance(x, (list, tuple, dict)) for x in arr):
            out = []
            for x in arr:
                try: out.append(float(x))
                except Exception: pass
            if out: return out
    for tkey, vkey in (("time","value"),("t","v"),("vectime","vecvalue"),("x","y")):
        varr = entry.get(vkey)
        if isinstance(varr, list) and varr:
            out = []
            for x in varr:
                try: out.append(float(x))
                except Exception: pass
            if out: return out
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

PRIMARY_SENT_NAMES = SCALAR_RX["sent_primary"]
FALLBACK_SENT_NAME = SCALAR_RX["sent_fallback"][0]

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
    ssum = hist_stat_sum(histograms, [re.compile(r"rx[_\s-]*started", re.I)])
    osum = hist_stat_sum(histograms, [re.compile(r"rx[_\s-]*ok", re.I)])
    if ssum is not None or osum is not None:
        return (int(ssum) if ssum is not None else None, int(osum) if osum is not None else None)
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

def pick_adr_commands(scalars: List[dict]) -> Tuple[Optional[int], Optional[int]]:
    adr_recv_total = 0; adr_recv_found = False
    for s in scalars:
        nm = str(s.get("name", "")); mod = str(s.get("module", ""))
        if re.search(r"\breceivedADRCommands\b", nm, re.I):
            if NODE_APP_MOD_RX.search(mod) or not mod:
                try:
                    val = float(s.get("value", 0))
                    adr_recv_total += int(val); adr_recv_found = True; _used_scalar(nm)
                except Exception: pass
    adr_sent_total = 0; adr_sent_found = False
    for s in scalars:
        nm = str(s.get("name", "")); mod = str(s.get("module", ""))
        if re.search(r"\bSend ADR for node\b", nm, re.I):
            if SERVER_MOD.search(mod) or not mod:
                try:
                    val = float(s.get("value", 0))
                    adr_sent_total += int(val); adr_sent_found = True; _used_scalar(nm)
                except Exception: pass
    return (adr_recv_total if adr_recv_found else None, adr_sent_total if adr_sent_found else None)

def extract_node_index(mod: str) -> Optional[int]:
    m = NODE_INDEX_RX.search(mod or "")
    if not m: return None
    try: return int(m.group(1))
    except Exception: return None

def sent_packets_by_node(scalars: List[dict]) -> Dict[int, int]:
    by_node: Dict[int, Dict[str, float]] = {}
    for s in scalars:
        mod = s.get("module", "") or ""; nm  = s.get("name", "") or ""; v   = s.get("value", None)
        if v is None or not NODE_APP_MOD_RX.fullmatch(mod): continue
        node = extract_node_index(mod)
        if node is None: continue
        slot = "primary" if any(rx.fullmatch(nm) for rx in PRIMARY_SENT_NAMES) else ("secondary" if FALLBACK_SENT_NAME.fullmatch(nm) else None)
        if not slot: continue
        try:
            val = float(v)
        except Exception:
            fv = parse_float_from_text(v); val = float(fv) if fv is not None else None
        if val is None: continue
        d = by_node.setdefault(node, {})
        if slot == "primary" and "primary" not in d:
            d["primary"] = val; d["primary_name"] = nm; _used_scalar(nm)
        elif slot == "secondary" and "primary" not in d and "secondary" not in d:
            d["secondary"] = val; d["secondary_name"] = nm; _used_scalar(nm)
    out: Dict[int, int] = {}
    for node, d in by_node.items():
        if "primary" in d: out[node] = int(d["primary"])
        elif "secondary" in d: out[node] = int(d["secondary"])
    return out

def received_packets_by_node(scalars: List[dict]) -> Dict[int, int]:
    out: Dict[int, int] = {}
    for s in scalars:
        nm = str(s.get("name", "") or "")
        mod = str(s.get("module", "") or "")
        if not SERVER_MOD.search(mod):
            continue
        if nm.startswith("numReceivedFromNode "):
            try:
                nid = int(nm.split("numReceivedFromNode ")[-1])
                val = int(float(s.get("value", 0)))
                out[nid] = val
                _used_scalar(nm)
            except Exception:
                continue
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
    cr = int(parse_float_from_text(crs) or 1)
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
# Config analysis / printing
# =============================================================================
def extract_init_conditions(params: List[dict], scalars: List[dict]) -> Dict[str, Any]:
    init_conditions = {}
    v = find_param_by_alias(params, PARAM_RX["nodes"])
    if v is not None: init_conditions["numberOfNodes"] = int(parse_float_from_text(v) or 0)
    v = find_param_by_alias(params, PARAM_RX["initial_sf"])
    if v is not None:
        n = parse_float_from_text(v)
        if n is not None: init_conditions["initialLoRaSF"] = int(n)
    v = find_param_by_alias(params, PARAM_RX["initial_tp"])
    if v is not None:
        n = parse_float_from_text(v)
        if n is not None: init_conditions["initialLoRaTP_dBm"] = float(n)
    v = find_param_by_alias(params, PARAM_RX["send_interval"])
    if v is not None:
        iv = parse_time_to_seconds(v)
        if iv is not None: init_conditions["sendInterval_s"] = float(iv)
    v = find_param_by_alias(params, PARAM_RX["adr_enabled"])
    if v is not None:
        b = parse_bool_text(v)
        if b is not None: init_conditions["evaluateADRinServer"] = bool(b)
    st = pick_scalar_by_alias(scalars, SCALAR_RX["sim_time"])
    if st is not None:
        init_conditions["simTime_s"] = float(st)
        init_conditions["simTime_min"] = float(st)/60.0
    v = find_param_by_alias(params, PARAM_RX["max_tx_dur"])
    if v is not None:
        sec = parse_time_to_seconds(v)
        if sec is not None: init_conditions["maxTransmissionDuration_s"] = float(sec)
    bw = find_param_by_alias(params, PARAM_RX["bandwidth"])
    if bw is not None:
        bw_hz = parse_bandwidth_to_hz(bw)
        if bw_hz is not None: init_conditions["bandwidth_Hz"] = float(bw_hz)
    cr = find_param_by_alias(params, PARAM_RX["coding_rate"])
    if cr is not None: init_conditions["codingRate"] = cr
    for p in params:
        nm = str(p.get("name",""))
        if "sigma" in nm.lower():
            val = parse_float_from_text(p.get("value",""))
            if val is not None:
                init_conditions["pathLoss_sigma_dB"] = float(val); _used_param(nm); break
    return init_conditions

def print_init_conditions(config_name: str, init_conditions: Dict[str, Any]) -> None:
    print(f"\n=== INITIALIZATION CONDITIONS: {config_name} ===")
    print("-" * 60)
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
    radio_params = [
        ("Initial SF", "initialLoRaSF", ""),
        ("Initial TP", "initialLoRaTP_dBm", "dBm"),
        ("Bandwidth", "bandwidth_Hz", "Hz"),
        ("Coding Rate", "codingRate", ""),
        ("Max TX Duration", "maxTransmissionDuration_s", "s"),
        ("Path Loss Sigma", "pathLoss_sigma_dB", "dB"),
    ]
    for label, key, unit in radio_params:
        val = init_conditions.get(key, "NOT FOUND")
        unit_str = f" {unit}" if unit and val != "NOT FOUND" else ""
        print(f"{label:<25}: {val}{unit_str}")
    if "simTime_s" in init_conditions and "sendInterval_s" in init_conditions:
        expected_packets = int(init_conditions["simTime_s"] / init_conditions["sendInterval_s"])
        print(f"{'Expected pkts/device':<25}: {expected_packets}")
    print("=" * 60)

def analyze_config(bundle: Dict[str, Path], label: str) -> Dict[str, Any]:
    res: Dict[str, Any] = {"Configuration": label}
    params_json     = read_json(bundle["parameters"]) if "parameters" in bundle else {}
    scalars_json    = read_json(bundle["scalars"])    if "scalars" in bundle    else {}
    histograms_json = read_json(bundle["histograms"]) if "histograms" in bundle else {}
    vectors_json    = read_json(bundle["app_vectors"])if "app_vectors" in bundle else {}
    params     = get_parameters_list(params_json)
    scalars    = get_scalars_list(scalars_json)
    histograms = get_histograms_list(histograms_json)
    vectors    = get_vectors_list(vectors_json)

    init_conditions = extract_init_conditions(params, scalars)
    print_init_conditions(label, init_conditions)
    if "simTime_s" in init_conditions:
        res["SimTime_s"] = float(init_conditions["simTime_s"])
        res["SimTime_min"] = float(init_conditions.get("simTime_min", init_conditions["simTime_s"] / 60.0))

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

    total_sent = sum_sent_packets_unique(scalars)
    if total_sent == 0:
        v = pick_scalar_by_alias(scalars, SCALAR_RX["sent_primary"]) or pick_scalar_by_alias(scalars, SCALAR_RX["sent_fallback"])
        if v is not None: total_sent = int(v)
    res["Total Sent"] = int(total_sent)

    tr = pick_total_received(scalars)
    if tr is not None: res["Total Received"] = int(tr)
    if res.get("Total Sent",0) > 0 and isinstance(res.get("Total Received"), int):
        res["Overall PDR (%)"] = 100.0 * res["Total Received"] / res["Total Sent"]
        res["Dropped"] = int(res["Total Sent"] - res["Total Received"])

    coll = pick_collisions(scalars)
    if coll is not None: res["Collisions"] = int(coll)

    rx_started, rx_ok = pick_gw_rx_metrics(scalars, histograms, vectors)
    if rx_started is not None: res["GW Rx Started"] = int(rx_started)
    if rx_ok is not None:      res["GW Rx OK"]      = int(rx_ok)
    if isinstance(res.get("GW Rx Started"), int) and res["GW Rx Started"]>0 and isinstance(res.get("GW Rx OK"), int):
        res["GW RxOK (%)"] = 100.0 * res["GW Rx OK"] / res["GW Rx Started"]

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

    sim_time_s = init_conditions.get("simTime_s")
    if isinstance(res.get("Total ToA (s)"), (int,float)) and isinstance(sim_time_s, (int,float)) and sim_time_s > 0:
        res["Busy (%)"] = 100.0 * float(res["Total ToA (s)"]) / float(sim_time_s)

    sf_counts = sf_counts_from_scalars(scalars)
    if sf_counts:
        total = sum(sf_counts.values())
        mean_sf = sum(sf*c for sf,c in sf_counts.items())/total if total>0 else None
        if mean_sf is not None: res["Mean SF"] = float(mean_sf)
        s79   = sum(c for sf,c in sf_counts.items() if 7<=sf<=9)
        s1012 = sum(c for sf,c in sf_counts.items() if 10<=sf<=12)
        if total>0:
            res["SF7-9 (%)"]   = 100.0*s79/total
            res["SF10-12 (%)"] = 100.0*s1012/total

    snr_mean_h = hist_stat_mean(histograms, HIST_RX["snr"])
    snr_med_h  = hist_stat_median(histograms, HIST_RX["snr"])
    snr_cnt_h  = hist_stat_count(histograms, HIST_RX["snr"])
    snr_mean_v, snr_med_v, snr_cnt_v = vector_stats(vectors, VEC_RX["snr"])
    if (snr_cnt_h or snr_cnt_v):
        if snr_cnt_h and snr_mean_h is not None and snr_cnt_v and snr_mean_v is not None:
            res["Mean SNIR (dB)"] = float((snr_mean_h*snr_cnt_h + snr_mean_v*snr_cnt_v)/float(snr_cnt_h+snr_cnt_v))
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

    adr_recv, adr_sent = pick_adr_commands(scalars)
    if adr_recv is not None:
        res["ADR Cmds (ED recv)"] = int(adr_recv)
        res["ADR Cmds"] = int(adr_recv)
    if adr_sent is not None:
        res["ADR Cmds (NS sent)"] = int(adr_sent)

    sent_by_node = sent_packets_by_node(scalars)
    recv_by_node = received_packets_by_node(scalars)
    if sent_by_node:
        n_nodes = len(sent_by_node)
        if n_nodes > 0:
            res["AvgMsgs/Node"] = float(res.get("Total Sent", 0)) / float(n_nodes)
        pdr_vals: List[float] = []
        low_count = 0
        for nid in sorted(set(sent_by_node) | set(recv_by_node)):
            s = sent_by_node.get(nid, 0)
            r = recv_by_node.get(nid, 0)
            p = (100.0 * r / s) if s > 0 else 0.0
            pdr_vals.append(p)
            if p < 80.0:
                low_count += 1
        if pdr_vals:
            pdr_vals.sort()
            res["Low-PDR (<80%)"] = int(low_count)
            res["PDR min (%)"] = float(pdr_vals[0])
            res["PDR med (%)"] = float(statistics.median(pdr_vals))
            res["PDR max (%)"] = float(pdr_vals[-1])

    return res

def fmt_num(x, digits=2):
    return f"{x:.{digits}f}" if isinstance(x, (int,float)) else "NA"

def print_context_table(rows: List[Dict[str, Any]], area: Optional[str]) -> None:
    title = "SCENARIO 05 - OMNeT++ FLoRa ANALYSIS RESULTS (context)"
    if area: title += f"  (area: {area})"
    print("\n" + "="*120)
    print(title)
    print("="*120)
    header = (
        "Configuration", "Nodes", "SimTime_s", "Interval_s", "ADR Enabled",
        "Initial SF", "Initial TP (dBm)", "Sent", "Received", "PDR(%)"
    )
    fmt = "{:<40} {:>5} {:>10} {:>11} {:>11} {:>10} {:>17} {:>10} {:>10} {:>8}"
    print(fmt.format(*header))

    def _key(r):
        v = r.get("Interval_s")
        try:
            return float(v) if v is not None else 1e12
        except Exception:
            return 1e12

    for r in sorted(rows, key=_key):
        sent = r.get("Total Sent")
        recv = r.get("Total Received")
        pdr = r.get("Overall PDR (%)")
        if pdr is None and isinstance(sent, (int, float)) and isinstance(recv, (int, float)) and sent > 0:
            pdr = 100.0 * float(recv) / float(sent)

        row = (
            r.get("Configuration",""),
            r.get("Nodes","NA"),
            f"{r.get('SimTime_s','NA'):.1f}" if isinstance(r.get("SimTime_s"), (int,float)) else "NA",
            f"{r.get('Interval_s','NA'):.1f}" if isinstance(r.get("Interval_s"), (int,float)) else "NA",
            str(r.get("ADR Enabled","NA")),
            r.get("Initial SF","NA"),
            f"{r.get('Initial TP (dBm)','NA'):.1f}" if isinstance(r.get("Initial TP (dBm)"), (int,float)) else "NA",
            f"{int(sent):d}" if isinstance(sent, (int,float)) else "NA",
            f"{int(recv):d}" if isinstance(recv, (int,float)) else "NA",
            f"{pdr:.2f}" if isinstance(pdr, (int,float)) else "NA",
        )
        print(fmt.format(*row))
    print("="*120)

def print_common_scoreboard(rows, area: Optional[str], title="SCENARIO 05 — Unified Scoreboard"):
    conf_w = max(28, min(64, max(len(r.get("Configuration","")) for r in rows)))
    title2 = title + (f"  (area: {area})" if area else "")
    hdr = ("Configuration", "Nodes", "Interval_s", "SimTime_min", "Sent", "Received", "Dropped", "PDR(%)")
    fmt = (
        f"{{:<{conf_w}}} "
        f"{{:>5}} "
        f"{{:>11}} "
        f"{{:>12}} "
        f"{{:>8}} "
        f"{{:>9}} "
        f"{{:>8}} "
        f"{{:>7}}"
    )
    header_line = fmt.format(*hdr)
    divider = "-" * len(header_line)

    print("\n" + "=" * len(header_line))
    print(title2)
    print("=" * len(header_line))
    print(header_line)
    print(divider)

    rows_sorted = sorted(rows, key=lambda r: (r.get("Interval_s") is None, r.get("Interval_s")))

    for r in rows_sorted:
        sim_min = r.get("SimTime_min")
        pdr     = r.get("PDR(%)")
        nodes   = r.get("Nodes")
        sent    = r.get("Sent")
        recv    = r.get("Received")
        drop    = r.get("Dropped")

        print(fmt.format(
            r.get("Configuration",""),
            f"{int(nodes):d}" if isinstance(nodes,(int,float)) else "NA",
            r.get("Interval_s","NA"),
            f"{sim_min:.2f}" if isinstance(sim_min,(int,float)) else "NA",
            f"{int(sent):d}" if isinstance(sent,(int,float)) else "NA",
            f"{int(recv):d}" if isinstance(recv,(int,float)) else "NA",
            f"{int(drop):d}" if isinstance(drop,(int,float)) else "NA",
            f"{pdr:.2f}" if isinstance(pdr,(int,float)) else "NA",
        ))

    print("=" * len(header_line))

# =============================================================================
# Main
# =============================================================================
def main():
    ap = argparse.ArgumentParser(description="Analyze OMNeT++/FLoRa Scenario 05 (Baseline variants) – area aware")
    ap.add_argument("--json-dir", type=Path, default=Path("json_exports"),
                    help="Directory with exported JSON files")
    ap.add_argument("--area", type=str, default=None,
                    help="Area tag to filter results (e.g. 1x1km, 2x2km, 1km). Matches *_<area>.*")
    ap.add_argument("--dump-keys", type=Path, default=None,
                    help="Save used keys to this JSON file")
    args = ap.parse_args()

    if not args.json_dir.exists():
        print(f"JSON directory not found: {args.json_dir}")
        print_used_keys()
        if args.dump_keys: dump_used_keys(args.dump_keys)
        sys.exit(2)

    area = args.area.strip() if args.area else None
    print(f"Searching for scenario-05 files in: {args.json_dir}")
    if area:
        print(f"Filtering by area tag(s): {', '.join(_area_token_variants(area))}")

    bundles = find_all_bundles_s05(args.json_dir, area)
    if not bundles:
        msg = "No Scenario-05 bundles found"
        if area: msg += f" for area '{area}'"
        msg += " (looked for 'scenario-05' + 'baseline' + '-s#')."
        print(msg)
        print_used_keys()
        if args.dump_keys: dump_used_keys(args.dump_keys)
        sys.exit(2)

    results: List[Dict[str, Any]] = []
    for label, bundle in bundles:
        results.append(analyze_config(bundle, label))

    common_rows = []
    for r in results:
        sent = int(r.get("Total Sent", 0))
        recv = int(r.get("Total Received", 0)) if isinstance(r.get("Total Received"), (int,float)) else 0
        drop = max(0, sent - recv)
        pdr = r.get("Overall PDR (%)")
        if pdr is None and sent > 0:
            pdr = 100.0 * recv / sent
        sim_s = r.get("SimTime_s")
        sim_min = (sim_s / 60.0) if isinstance(sim_s, (int,float)) else None
        nodes = r.get("Nodes")

        common_rows.append({
            "Configuration": r.get("Configuration",""),
            "Nodes": int(nodes) if isinstance(nodes,(int,float)) else None,
            "Interval_s": int(r["Interval_s"]) if isinstance(r.get("Interval_s"), (int,float)) else None,
            "SimTime_min": sim_min,
            "Sent": sent,
            "Received": recv,
            "Dropped": drop,
            "PDR(%)": pdr,
        })

    if not results:
        print("No valid results to analyze.")
        print_used_keys()
        if args.dump_keys: dump_used_keys(args.dump_keys)
        sys.exit(2)

    # Context table
    print_context_table(results, area)

    # Scoreboard
    print_common_scoreboard(common_rows, area)

    # Keys used
    print_used_keys()
    if args.dump_keys: dump_used_keys(args.dump_keys)

if __name__ == "__main__":
    main()
