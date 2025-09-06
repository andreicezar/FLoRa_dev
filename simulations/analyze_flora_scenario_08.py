#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scenario-08 Analyzer (Multi-Gateway Coordination) — CLEAN v4
- Network PDR only (no radio PER)
- Coverage(%), BalanceScore (Jain fairness from per-GW DER)
- Uses RSSI/SNIR (hist/vector), SF/TP means, DER totals + per-SF (not printed)
"""

from __future__ import annotations
import argparse, json, re, statistics
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

# ============================================================================ #
# key tracking (for debug / audit)
# ============================================================================ #
USED_KEYS: Dict[str, set] = {"parameters": set(), "scalars": set(), "histograms": set(), "vectors": set()}
def _used_param(n): USED_KEYS["parameters"].add(str(n)) if n else None
def _used_scalar(n): USED_KEYS["scalars"].add(str(n)) if n else None
def _used_hist(n): USED_KEYS["histograms"].add(str(n)) if n else None
def _used_vector(n): USED_KEYS["vectors"].add(str(n)) if n else None

# ============================================================================ #
# json helpers
# ============================================================================ #
def read_json(p: Path):
    with open(p, "r", encoding="utf-8") as f: return json.load(f)

def _get_block(obj: Any, key: str) -> Optional[dict]:
    if isinstance(obj, dict):
        if key in obj and isinstance(obj[key], list): return obj
        for v in obj.values():
            if isinstance(v, dict) and key in v and isinstance(v[key], list): return v
    return None

def get_parameters_list(obj: Any) -> List[dict]:
    blk = _get_block(obj, "parameters"); return blk.get("parameters", []) if blk else []

def get_scalars_list(obj: Any) -> List[dict]:
    blk = _get_block(obj, "scalars"); return blk.get("scalars", []) if blk else []

def get_histograms_list(obj: Any) -> List[dict]:
    blk = _get_block(obj, "histograms")
    if blk and isinstance(blk.get("histograms"), list): return blk["histograms"]
    blk = _get_block(obj, "statistics")
    if blk and isinstance(blk.get("statistics"), list): return blk["statistics"]
    if isinstance(obj, dict):
        if isinstance(obj.get("histograms"), list): return obj["histograms"]
        if isinstance(obj.get("statistics"), list): return obj["statistics"]
    return []

def get_vectors_list(obj: Any) -> List[dict]:
    for key in ("vectors", "app_vectors"):
        blk = _get_block(obj, key)
        if blk and isinstance(blk.get(key), list): return blk[key]
        if isinstance(obj, dict) and isinstance(obj.get(key), list): return obj[key]
    return []

# ============================================================================ #
# parsing helpers
# ============================================================================ #
_TIME_RX = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([a-zA-Z]+)?\s*$")
def parse_time_seconds(s: Any) -> Optional[float]:
    if s is None: return None
    if isinstance(s,(int,float)): return float(s)
    m = _TIME_RX.match(str(s))
    if not m: return None
    val, unit = float(m.group(1)), (m.group(2) or "").lower()
    if unit in ("","s","sec","secs","second","seconds"): return val
    if unit in ("ms","msec","millisecond","milliseconds"): return val/1000.0
    if unit in ("min","m","minute","minutes"): return val*60.0
    if unit in ("h","hr","hour","hours"): return val*3600.0
    return None

_NUM_RX = re.compile(r"[-+]?[0-9]+(?:\.[0-9]+)?")
def parse_float(s: Any) -> Optional[float]:
    if s is None: return None
    if isinstance(s,(int,float)): return float(s)
    m = _NUM_RX.search(str(s)); return float(m.group(0)) if m else None

def parse_bool(s: Any) -> Optional[bool]:
    if isinstance(s,bool): return s
    if s is None: return None
    t = str(s).strip().lower()
    if t in ("true","yes","1","on"): return True
    if t in ("false","no","0","off"): return False
    return None

# ============================================================================ #
# discovery
# ============================================================================ #
def find_bundle(json_dir: Path, base_name: str) -> Dict[str, Path]:
    out: Dict[str, Path] = {}
    for p in json_dir.glob(f"{base_name}_*.json"):
        low = p.name.lower()
        if "parameters" in low and "parameters" not in out: out["parameters"] = p
        elif "scalars" in low and "scalars" not in out: out["scalars"] = p
        elif ("histograms" in low or "statistics" in low) and "histograms" not in out: out["histograms"] = p
        elif "app_vectors" in low and "app_vectors" not in out: out["app_vectors"] = p
        elif "vectors" in low and "app_vectors" not in out: out["app_vectors"] = p
    return out

def find_all_bundles(json_dir: Path) -> List[Tuple[str, Dict[str, Path]]]:
    bases = set()
    for p in json_dir.glob("*.json"):
        n = p.name; low = n.lower()
        if "scenario-08" in low or ("multi" in low and "gateway" in low):
            base = re.sub(r"_(parameters|scalars|histograms|statistics|app_vectors|vectors|extracted)\.json$", "", n, flags=re.I)
            bases.add(base)
    out = []
    for base in sorted(bases):
        b = find_bundle(json_dir, base)
        if b.get("parameters") and b.get("scalars"):
            out.append((base,b))
    return out

# ============================================================================ #
# alias maps
# ============================================================================ #
PARAM_RX = {
    "nodes":[re.compile(r"\bnumberOfNodes\b",re.I), re.compile(r"\bnDevices\b",re.I)],
    "gateways":[re.compile(r"\bnumberOfGateways\b",re.I), re.compile(r"\bnGateways\b",re.I)],
    "send_interval":[re.compile(r"\btimeToNextPacket\b",re.I), re.compile(r"\bsendInterval\b",re.I)],
    "initial_sf":[re.compile(r"\binitialLoRaSF\b",re.I)],
    "initial_tp":[re.compile(r"\binitialLoRaTP\b",re.I)],
    "adr_enabled":[re.compile(r"\badrEnabled\b",re.I), re.compile(r"\benableADR\b",re.I)],
}

SCALAR_RX = {
    "sim_time":[re.compile(r"\bsimulated time\b",re.I)],
    "sent":[re.compile(r"^sentPackets$",re.I), re.compile(r"^packetsSent$",re.I)],
    "total_received":[re.compile(r"\btotalReceivedPackets\b",re.I), re.compile(r"\bLoRa_ServerPacketReceived:count\b",re.I)],
    # DERs (server-level)
    "der_total":[re.compile(r"^DER\s*-\s*Data\s*Extraction\s*Rate$",re.I)],
    "der_gw":[re.compile(r"^LoRa_GW_DER$",re.I)],
    "der_ns":[re.compile(r"^LoRa_NS_DER$",re.I)],
    "der_per_sf":[re.compile(r"^DER\s*SF(7|8|9|10|11|12)$",re.I)],
}

SERVER_MOD = re.compile(r"LoRaNetworkTest\.networkServer\.app\[0\]", re.I)
NODE_APP_MOD = re.compile(r".*\.loRaNodes\[\d+\]\.app\[0\]$", re.I)

# ============================================================================ #
# small helpers
# ============================================================================ #
def find_param(params: Iterable[Dict[str, Any]], patterns: List[re.Pattern]) -> Optional[str]:
    for rx in patterns:
        for p in params:
            nm = str(p.get("name",""))
            if rx.search(nm):
                _used_param(nm); return str(p.get("value",""))
    return None

def pick_scalar(scalars: Iterable[Dict[str, Any]], patterns: List[re.Pattern], module_rx: Optional[re.Pattern]=None) -> Optional[float]:
    for rx in patterns:
        for s in scalars:
            nm = str(s.get("name","")); mod = str(s.get("module",""))
            if module_rx is not None and not module_rx.search(mod): continue
            if rx.search(nm) and s.get("value") is not None:
                _used_scalar(nm)
                try: return float(s["value"])
                except Exception:
                    v = parse_float(s["value"]); 
                    if v is not None: return float(v)
    return None

def sum_unique_sent(scalars: List[dict]) -> int:
    per_node: Dict[str, float] = {}
    for s in scalars:
        mod = s.get("module","") or ""
        nm = s.get("name","") or ""
        v = s.get("value", None)
        if v is None or not NODE_APP_MOD.fullmatch(mod): continue
        if any(rx.fullmatch(nm) for rx in SCALAR_RX["sent"]):
            if mod not in per_node:
                per_node[mod] = float(v); _used_scalar(nm)
    return int(sum(per_node.values()))

def _hist_mean(h: dict) -> Optional[float]:
    m = h.get("mean")
    if isinstance(m,(int,float)): return float(m)
    sw, ws = h.get("sumWeights"), h.get("weightedSum")
    if isinstance(sw,(int,float)) and sw>0 and isinstance(ws,(int,float)): return float(ws)/float(sw)
    bins = h.get("binvalues") or h.get("values") or []; edges = h.get("binedges") or []
    if bins and edges and len(edges)>=2:
        centers = [(edges[i]+edges[i+1])/2 for i in range(len(edges)-1)]
        num = den = 0.0
        for c,w in zip(centers,bins):
            if isinstance(c,(int,float)) and isinstance(w,(int,float)):
                num += c*w; den += w
        if den>0: return num/den
    return None

def mean_from_vector_entries(vectors: List[dict], name_rx: re.Pattern) -> Tuple[Optional[float], int]:
    vals: List[float] = []
    for v in vectors:
        if name_rx.fullmatch(str(v.get("name",""))):
            _used_vector(v.get("name",""))
            arr = v.get("value") or v.get("y") or []
            if isinstance(arr, list):
                for x in arr:
                    if isinstance(x,(int,float)): vals.append(float(x))
    if vals: return statistics.fmean(vals), len(vals)
    return None, 0

def extract_rssi_snir(histograms: List[dict], vectors: List[dict]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    # RSSI: prefer histogram "receivedRSSI"
    rssi_mean = None
    for h in histograms:
        if re.fullmatch(r"receivedRSSI", str(h.get("name","")), re.I):
            _used_hist(h.get("name","")); rssi_mean = _hist_mean(h); break
    if rssi_mean is None:
        rssi_mean, rssi_n = mean_from_vector_entries(vectors, re.compile(r"^Vector of RSSI per node$", re.I))
        if rssi_mean is not None: out["RSSI_Samples"] = rssi_n
    if rssi_mean is not None: out["RSSI_Mean(dBm)"] = rssi_mean

    # SNIR: histogram fallback to vector
    snir_mean = None
    for h in histograms:
        if re.fullmatch(r"minSnir:histogram", str(h.get("name","")), re.I):
            _used_hist(h.get("name","")); snir_mean = _hist_mean(h); break
    if snir_mean is None:
        snir_mean, snir_n = mean_from_vector_entries(vectors, re.compile(r"^Vector of SNIR per node$", re.I))
        if snir_mean is not None: out["SNIR_Samples"] = snir_n
    if snir_mean is not None: out["SNIR_Mean(dB)"] = snir_mean
    return out

def nodes_heard_from_scalars(scalars: List[dict]) -> int:
    heard = 0
    for s in scalars:
        nm = str(s.get("name",""))
        if re.fullmatch(r"^numReceivedFromNode\s+\d+$", nm, flags=re.I):
            try:
                if float(s.get("value",0)) > 0:
                    _used_scalar(nm); heard += 1
            except: pass
    return heard

def der_from_scalars(scalars: List[dict]) -> Dict[str, Any]:
    out={}
    # total DER must be from the server (network-level)
    out["DER_Total(%)"] = pick_scalar(scalars, SCALAR_RX["der_total"], module_rx=SERVER_MOD)
    out["DER_Gateway(%)"] = pick_scalar(scalars, SCALAR_RX["der_gw"])
    out["DER_NetworkServer(%)"] = pick_scalar(scalars, SCALAR_RX["der_ns"])
    # per-SF DERs (also server-level)
    for s in scalars:
        nm=str(s.get("name","")); val=s.get("value", None)
        if val is None: continue
        if SERVER_MOD.search(str(s.get("module",""))):
            m=re.fullmatch(r"DER\s*SF(7|8|9|10|11|12)", nm, re.I)
            if m: _used_scalar(nm); out[f"DER_SF{m.group(1)}(%)"]=float(val)
    return out

def sf_tp_means(vectors: List[dict]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    sf_mean, sf_n = mean_from_vector_entries(vectors, re.compile(r"^SF Vector$", re.I))
    if sf_mean is not None: out["SF_Mean"] = sf_mean; out["SF_Samples"] = sf_n
    tp_mean, tp_n = mean_from_vector_entries(vectors, re.compile(r"^TP Vector$", re.I))
    if tp_mean is not None: out["TP_Mean(dBm)"] = tp_mean; out["TP_Samples"] = tp_n
    return out

def jain_index(values: List[float]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    if not vals or sum(vals) <= 0: return None
    num = (sum(vals))**2
    den = len(vals) * sum(v*v for v in vals)
    if den == 0: return None
    return num/den

# --- Per-gateway DER extraction (DER % per gateway) ---
GW_DER_NAME_RX = [
    re.compile(r"(?i)^\s*der\s*-\s*data\s*extraction\s*rate(?:[:\s].*)?$"),  # "DER - Data Extraction Rate"
    re.compile(r"(?i)^\s*lora[\s_]*gw[\s_]*der(?:[:\s].*)?$"),               # "LoRa_GW_DER" or "LoRa GW DER"
    re.compile(r"(?i)^\s*der(?:[:\s].*)?$"),                                 # plain "DER"
]

def gw_der_percent_by_id(scalars: list[dict]) -> dict[int, float]:
    """
    Returns {gw_id: DER_percent}. Accepts values as fraction (0..1) or percent (0..100).
    Matches modules like 'LoRaNetworkTest.loRaGW[<id>].*' and DER names with flexible spacing/suffixes.
    """
    out: dict[int, float] = {}
    for s in scalars:
        mod = str(s.get("module", "") or "")
        nm  = str(s.get("name", "") or "")
        nm_norm = re.sub(r"\s+", " ", nm).strip()
        m = re.search(r"\bloRaGW\[(\d+)\]", mod, flags=re.I)
        if not m:
            continue
        if not any(rx.match(nm_norm) for rx in GW_DER_NAME_RX):
            continue
        try:
            gid = int(m.group(1))
            val = float(s.get("value", 0))
        except Exception:
            continue
        if 0.0 <= val <= 1.0:  # normalize fraction -> percent
            val *= 100.0
        _used_scalar(nm)
        out[gid] = val
    return out

# ============================================================================ #
# core analysis
# ============================================================================ #
def analyze_config(bundle: Dict[str, Path], label: str) -> Dict[str, Any]:
    print(f"\n=== ANALYZING: {label} ===")
    params = get_parameters_list(read_json(bundle["parameters"])) if "parameters" in bundle else []
    scalars = get_scalars_list(read_json(bundle["scalars"])) if "scalars" in bundle else []
    histograms = get_histograms_list(read_json(bundle["histograms"])) if "histograms" in bundle else []
    vectors = get_vectors_list(read_json(bundle["app_vectors"])) if "app_vectors" in bundle else []

    print(f"  Loaded: {len(params)} params, {len(scalars)} scalars, {len(histograms)} histograms, {len(vectors)} vectors")

    res: Dict[str, Any] = {"Configuration": label}

    v = find_param(params, PARAM_RX["gateways"]); res["Gateways"] = int(parse_float(v) or 1) if v is not None else 1
    v = find_param(params, PARAM_RX["nodes"]);    res["Nodes"]    = int(parse_float(v) or 0) if v is not None else None
    v = find_param(params, PARAM_RX["send_interval"]); iv = parse_time_seconds(v) if v is not None else None
    if iv is not None: res["Interval_s"] = iv
    v = find_param(params, PARAM_RX["initial_sf"]); 
    if v is not None: res["Initial_SF"] = int(parse_float(v) or 0)
    v = find_param(params, PARAM_RX["initial_tp"]); 
    if v is not None: res["Initial_TP(dBm)"] = float(parse_float(v) or 0.0)
    v = find_param(params, PARAM_RX["adr_enabled"]); 
    if v is not None: res["ADR_Enabled"] = parse_bool(v)

    st = pick_scalar(scalars, SCALAR_RX["sim_time"])
    if st is not None: res["SimTime_s"] = float(st); res["SimTime_min"] = float(st)/60.0

    total_sent = sum_unique_sent(scalars)
    if total_sent == 0:
        v = pick_scalar(scalars, SCALAR_RX["sent"])
        if v is not None: total_sent = int(v)
    res["TotalSent"] = int(total_sent)
    tr = pick_scalar(scalars, SCALAR_RX["total_received"], module_rx=re.compile(r"LoRaNetworkTest\.networkServer", re.I)) or pick_scalar(scalars, SCALAR_RX["total_received"])
    if tr is not None: res["TotalReceived"] = int(tr)
    if res.get("TotalSent",0) and res.get("TotalReceived") is not None:
        res["UniquePDR(%)"] = 100.0 * res["TotalReceived"]/res["TotalSent"]

    nh = nodes_heard_from_scalars(scalars)
    if nh:
        res["NodesHeard"] = nh
        if res.get("Nodes"): res["Coverage(%)"] = 100.0*nh/res["Nodes"]

    res.update(extract_rssi_snir(histograms, vectors))
    res.update(sf_tp_means(vectors))
    res.update({k:v for k,v in der_from_scalars(scalars).items() if v is not None})

    # ===== BalanceScore derived STRICTLY from per-GW DER =====
    gw_der = gw_der_percent_by_id(scalars)  # {gw_id: DER%}
    if gw_der:
        vals = list(gw_der.values())
        if len(vals) >= 2:
            bal = jain_index(vals)
            if bal is not None:
                res["BalanceScore"] = 1.0 - bal     # 0.0 = perfectly balanced
        else:
            res["BalanceScore"] = None  # NA for single-GW

    print(f"  Packets: {res.get('TotalSent',0)} sent, {res.get('TotalReceived',0)} received")
    print(f"  PDR: {res.get('UniquePDR(%)',0):.2f}%")
    return res

# ============================================================================ #
# reporting
# ============================================================================ #
def print_scoreboard(rows: List[Dict[str, Any]]):
    rows = [r for r in rows if isinstance(r, dict)]
    if not rows:
        print("No rows."); return

    # Column spec: (header, key, formatter, align)
    # Left-align only the first (Configuration); right-align everything else.
    cols = [
        ("Configuration", "Configuration", lambda v: str(v) if v is not None else "", "<"),
        ("GWs",           "Gateways",      lambda v: f"{int(v)}" if isinstance(v,(int,float)) else "NA", ">"),
        ("Nodes",         "Nodes",         lambda v: f"{int(v)}" if isinstance(v,(int,float)) else "NA", ">"),
        ("Sent",          "TotalSent",     lambda v: f"{int(v)}" if isinstance(v,(int,float)) else "NA", ">"),
        ("Recv",          "TotalReceived", lambda v: f"{int(v)}" if isinstance(v,(int,float)) else "NA", ">"),
        ("UniquePDR(%)",  "UniquePDR(%)",  lambda v: f"{v:.1f}" if isinstance(v,(int,float)) else "NA", ">"),
        ("Coverage(%)",   "Coverage(%)",   lambda v: f"{v:.1f}" if isinstance(v,(int,float)) else "NA", ">"),
        ("NodesHeard",    "NodesHeard",    lambda v: f"{int(v)}" if isinstance(v,(int,float)) else "NA", ">"),
        ("RSSI",          "RSSI_Mean(dBm)",lambda v: f"{v:.1f}" if isinstance(v,(int,float)) else "NA", ">"),
        ("SNIR",          "SNIR_Mean(dB)", lambda v: f"{v:.1f}" if isinstance(v,(int,float)) else "NA", ">"),
        ("SF",            "SF_Mean",       lambda v: f"{v:.1f}" if isinstance(v,(int,float)) else "NA", ">"),
        ("TP(dBm)",       "TP_Mean(dBm)",  lambda v: f"{v:.1f}" if isinstance(v,(int,float)) else "NA", ">"),
        ("BalanceScore",  "BalanceScore",  lambda v: f"{v:.4f}" if isinstance(v,(int,float)) else "NA", ">"),
    ]

    # Build table cells
    data_rows = []
    for r in sorted(rows, key=lambda x: (x.get("Gateways",0), x.get("Configuration",""))):
        data_rows.append([ fmt(r.get(key)) for (hdr, key, fmt, _) in cols ])

    # Compute widths from header + cells
    widths = []
    for j, (hdr, _, _, _) in enumerate(cols):
        cell_max = max(len(row[j]) for row in data_rows) if data_rows else 0
        widths.append(max(len(hdr), cell_max))

    # Build format string with separators
    parts = []
    for (hdr, _, _, align), w in zip(cols, widths):
        parts.append(f"{{:{align}{w}}}")
    fmt = " " + " | ".join(parts)  # leading space for a neat margin

    header = fmt.format(*[hdr for (hdr, _, _, _) in cols])
    line = "-" * len(header)

    print("\n"+ "="*len(header))
    print("SCENARIO 08 – Multi-Gateway Coordination (OMNeT++ FLoRa) — CLEAN v4")
    print("="*len(header))
    print(header)
    print(line)
    for row in data_rows:
        print(fmt.format(*row))
    print("="*len(header))

def print_used_keys():
    print("\n=== Used keys (this run) ===")
    for t in ["parameters","scalars","histograms","vectors"]:
        vals = sorted(USED_KEYS[t])
        if vals:
            print(f"{t.capitalize()}:")
            for k in vals: print(f"  - {k}")
        else:
            print(f"{t.capitalize()}: (none)")

# ============================================================================ #
# main
# ============================================================================ #
def main():
    ap = argparse.ArgumentParser(description="Analyze OMNeT++/FLoRa Scenario 08 (clean v4)")
    ap.add_argument("--json-dir", type=Path, default=Path("json_exports"))
    ap.add_argument("--dump-keys", type=Path, default=None)
    args = ap.parse_args()

    if not args.json_dir.exists():
        print(f"JSON directory not found: {args.json_dir}")
        return

    print(f"Searching for scenario-08 files in: {args.json_dir}")
    bundles = find_all_bundles(args.json_dir)
    if not bundles:
        print("No Scenario-08 bundles found."); return

    print(f"Found {len(bundles)} candidate configurations.")
    results: List[Dict[str, Any]] = []
    for label, bundle in bundles:
        print(f"  - {label}")
        res = analyze_config(bundle, label)
        results.append(res)

    print_scoreboard(results)
    print_used_keys()
    if args.dump_keys:
        with open(args.dump_keys, "w", encoding="utf-8") as f:
            json.dump({k: sorted(v) for k, v in USED_KEYS.items()}, f, ensure_ascii=False, indent=2)
        print(f"[keys] saved -> {args.dump_keys}")

if __name__ == "__main__":
    main()
