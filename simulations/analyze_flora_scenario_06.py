#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
OMNeT++ FLoRa — Scenario 06 (Collision / Capture) Analyzer — AREA-AWARE

What this does:
- Adds --area filtering (e.g., 1x1km..5x5km). Also accepts compact aliases like _1km.
- Positions: parameters-first (supports both classic module+name and "full-path key" entries),
  with scalar fallback. Works with keys like {"**.loRaNodes[0].**.initialX": "143.29m"}.
- Near/Far cohorts by distance quartiles; CaptureΔ = NearPDR − FarPDR.
- Sent/Recv totals: consider multiple scalar candidates; prefer server-deduped Recv; guard Sent >= Recv.
- Optional: --print-positions dumps all GW and node XY for each run.

Usage:
  python3 analyze_flora_scenario_06.py --json-dir json_exports --area 1x1km
  python3 analyze_flora_scenario_06.py --json-dir json_exports --print-positions
"""

from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import argparse, json, re, math

# -------------------------
# Basic helpers
# -------------------------
def read_json(p: Path) -> Any:
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

def list_in(obj: Any, key: str) -> List[dict]:
    if isinstance(obj, dict):
        if isinstance(obj.get(key), list):
            return obj[key]
        for v in obj.values():
            if isinstance(v, dict) and isinstance(v.get(key), list):
                return v[key]
    return []

def to_float(v) -> Optional[float]:
    if v is None: return None
    if isinstance(v, (int, float)): return float(v)
    s = str(v)
    # strip common units
    for tok in ("dBm", "dbm", "m"):
        s = s.replace(tok, "")
    s = s.strip()
    try:
        return float(s)
    except Exception:
        m = re.search(r"[-+]?\d+(?:\.\d+)?", s)
        return float(m.group(0)) if m else None

def parse_time_seconds(v) -> Optional[float]:
    if v is None: return None
    if isinstance(v, (int, float)): return float(v)
    s = str(v).strip()
    m = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z]+)?\s*$", s)
    if not m: return None
    val = float(m.group(1)); unit = (m.group(2) or "").lower()
    if unit in ("","s","sec","secs","second","seconds"): return val
    if unit in ("ms","msec","millisecond","milliseconds"): return val/1000.0
    if unit in ("m","min","minute","minutes"): return val*60.0
    if unit in ("h","hr","hour","hours"): return val*3600.0
    return None

# =============================================================================
# Area filtering helpers (same style as scenario 08)
# =============================================================================
def _area_aliases(area: str) -> set[str]:
    """
    Accept '1x1km' plus compact alias '1km' (since your files sometimes use _1km).
    """
    a = area.lower().strip().strip("_- ")
    aliases = {a}
    if "x" in a and a.endswith("km"):
        first = a.split("x", 1)[0]  # '1x1km' -> '1'
        aliases.add(f"{first}km")
    return aliases

def name_matches_area(filename: str, area: Optional[str]) -> bool:
    """
    True if filename matches requested area (or no area requested).
    We check for substrings like '_1x1km' OR '_1km'.
    """
    if not area:
        return True
    n = filename.lower()
    for alias in _area_aliases(area):
        if f"_{alias}" in n:
            return True
    return False

# -------------------------
# Bundle discovery (AREA-AWARE)
# -------------------------
def find_bundles(json_dir: Path, area: Optional[str]) -> List[Tuple[str, Dict[str, Path]]]:
    """
    Discover Scenario-06 collision bundles, filtered by --area.
    A "base" is the common prefix of the 4 JSON files (parameters/scalars/ histograms/vectors),
    possibly including the area suffix (e.g., ...-s0_1x1km).
    """
    bases = set()
    for p in json_dir.glob("*.json"):
        low = p.name.lower()
        if "scenario-06" in low and "collision" in low and re.search(r"-s\d+", low):
            if not name_matches_area(p.name, area):
                continue
            # strip trailing "_<type>.json" and optional "_<area>"
            base = re.sub(
                r"_(?:[0-9]+x[0-9]+km|[0-9]+km)?_(parameters|scalars|histograms|statistics|vectors|app_vectors)\.json$",
                "",
                p.name,
                flags=re.I,
            )
            # If the above didn't match (some exporters omit area), fall back to just stripping the type
            base = re.sub(
                r"_(parameters|scalars|histograms|statistics|vectors|app_vectors)\.json$",
                "",
                base,
                flags=re.I,
            )
            bases.add(base)

    out: List[Tuple[str, Dict[str, Path]]] = []
    for base in sorted(bases):
        toks = [t for t in base.lower().split("-") if t]
        bundle: Dict[str, Path] = {}
        for p in json_dir.glob("*.json"):
            low = p.name.lower()
            if not name_matches_area(p.name, area):
                continue
            # must contain all base tokens (robust match)
            if all(t in low for t in toks):
                if "parameters" in low and "parameters" not in bundle: bundle["parameters"] = p
                elif "scalars" in low and "scalars" not in bundle: bundle["scalars"] = p
                elif ("app_vectors" in low or "vectors" in low) and "vectors" not in bundle: bundle["vectors"] = p
                elif ("histograms" in low or "statistics" in low) and "histograms" not in bundle: bundle["histograms"] = p
        # require at least params + scalars
        if bundle.get("parameters") and bundle.get("scalars"):
            out.append((base, bundle))
    return out

# -------------------------
# Parameters iterator (handles classic and one-key dict)
# -------------------------
def iter_param_kv(parameters: List[dict]):
    """
    Yields (name, value) from parameter entries in BOTH forms:
      A) {"name": "...", "value": "..."}               (classic)
      B) {"<full.path>": "<value>"}                    (one-key dict)
    """
    for p in parameters:
        if isinstance(p, dict):
            if "name" in p:
                yield str(p.get("name") or ""), p.get("value")
            elif len(p) == 1:
                k, v = next(iter(p.items()))
                yield str(k or ""), v

# -------------------------
# Position extraction
# -------------------------
NODE_IN_MODULE_RX = re.compile(r"loRaNodes\[(\d+)\]", re.I)
GW_IN_MODULE_RX   = re.compile(r"loRaGW(?:\[\d+\])?|loRaGWs\[\d+\]", re.I)

PARAM_NODE_KV_RX = re.compile(
    r"loRaNodes\[(\d+)\].*?\.(initialX|initialY|positionX|positionY|posX|posY|x|y)",
    re.I,
)
PARAM_GW_KV_RX = re.compile(
    r"(loRaGW(?:\[\d+\])?|loRaGWs\[\d+\]).*?\.(initialX|initialY|positionX|positionY|posX|posY|x|y)",
    re.I,
)

POS_NAME_SET = {"initialx","initialy","positionx","positiony","posx","posy","x","y"}

def extract_node_positions(parameters: List[dict], scalars: List[dict]) -> Dict[int, Tuple[float,float]]:
    posx: Dict[int, float] = {}
    posy: Dict[int, float] = {}

    # --- PARAMETERS: classic (module + name) ---
    for p in parameters:
        mod = str(p.get("module","") or "")
        nm  = str(p.get("name","") or "")
        nml = nm.lower()
        val = to_float(p.get("value"))
        if not mod and not nm:
            continue
        m_mod = NODE_IN_MODULE_RX.search(mod)
        if m_mod and nml in POS_NAME_SET and val is not None:
            idx = int(m_mod.group(1))
            if nml in ("initialx","positionx","posx","x"): posx[idx] = val
            elif nml in ("initialy","positiony","posy","y"): posy[idx] = val

    # --- PARAMETERS: one-key dict entries ---
    for name, value in iter_param_kv(parameters):
        if not name or value is None:
            continue
        mk = PARAM_NODE_KV_RX.search(name)
        if not mk:
            continue
        idx = int(mk.group(1))
        last = mk.group(2).lower()
        v = to_float(value)
        if v is None:
            continue
        if last in ("initialx","positionx","posx","x"): posx[idx] = v
        elif last in ("initialy","positiony","posy","y"): posy[idx] = v

    out = {n: (posx[n], posy[n]) for n in sorted(set(posx) & set(posy))}
    if out:
        return out

    # --- SCALARS fallback ---
    posx, posy = {}, {}
    for s in scalars:
        mod = str(s.get("module","") or "")
        nm  = str(s.get("name","") or "")
        nml = nm.lower()
        val = to_float(s.get("value"))
        m_mod = NODE_IN_MODULE_RX.search(mod)
        if m_mod and nml in POS_NAME_SET and val is not None:
            idx = int(m_mod.group(1))
            if nml in ("initialx","positionx","posx","x"): posx[idx] = val
            elif nml in ("initialy","positiony","posy","y"): posy[idx] = val
            continue
        # allow name path in scalar name too (rare)
        m_name = PARAM_NODE_KV_RX.search(nm)
        if m_name and val is not None:
            idx2 = int(m_name.group(1))
            last2 = m_name.group(2).lower()
            if last2 in ("initialx","positionx","posx","x"): posx[idx2] = val
            elif last2 in ("initialy","positiony","posy","y"): posy[idx2] = val

    return {n: (posx[n], posy[n]) for n in sorted(set(posx) & set(posy))}

def extract_gateway_xy(parameters: List[dict], scalars: List[dict]) -> Optional[Tuple[float,float]]:
    gx = gy = None

    # --- PARAMETERS: classic (module + name) ---
    for p in parameters:
        mod = str(p.get("module","") or "")
        nm  = str(p.get("name","") or "")
        nml = nm.lower()
        val = to_float(p.get("value"))
        if val is None:
            continue
        if GW_IN_MODULE_RX.search(mod) and nml in POS_NAME_SET:
            if nml in ("initialx","positionx","posx","x"): gx = val
            elif nml in ("initialy","positiony","posy","y"): gy = val

    # --- PARAMETERS: one-key dict entries ---
    for name, value in iter_param_kv(parameters):
        if not name or value is None:
            continue
        mk = PARAM_GW_KV_RX.search(name)
        if not mk:
            continue
        last = (mk.group(2).lower() if mk.lastindex and mk.lastindex >= 2 else name.split(".")[-1].lower())
        v = to_float(value)
        if v is None:
            continue
        if last in ("initialx","positionx","posx","x"): gx = v
        elif last in ("initialy","positiony","posy","y"): gy = v

    if gx is not None and gy is not None:
        return (gx, gy)

    # --- SCALARS fallback ---
    for s in scalars:
        mod = str(s.get("module","") or "")
        nm  = str(s.get("name","") or "").lower()
        val = to_float(s.get("value"))
        if val is None:
            continue
        if GW_IN_MODULE_RX.search(mod) and nm in POS_NAME_SET:
            if nm in ("initialx","positionx","posx","x"): gx = val
            elif nm in ("initialy","positiony","posy","y"): gy = val

    return (gx, gy) if (gx is not None and gy is not None) else None

# -------------------------
# Scalar helpers for totals
# -------------------------
def sent_by_node_from_scalars(scalars: List[dict]) -> Dict[int,int]:
    out: Dict[int,int] = {}
    for s in scalars:
        mod = str(s.get("module","") or "")
        nm  = str(s.get("name","") or "")
        m = NODE_IN_MODULE_RX.search(mod)
        if not m: continue
        if re.fullmatch(r"(sentPackets|numSent|txPk:count)", nm, re.I):
            try: out[int(m.group(1))] = int(float(s.get("value")))
            except: pass
    return out

def recv_by_node_from_scalars(scalars: List[dict]) -> Dict[int,int]:
    out: Dict[int,int] = {}
    for s in scalars:
        nm = str(s.get("name","") or "")
        m = re.match(r"^numReceivedFromNode\s+(\d+)$", nm, re.I)
        if not m: continue
        try: out[int(m.group(1))] = int(float(s.get("value")))
        except: pass
    return out

def pick_scalar(scalars: List[dict], names: List[str]) -> Optional[float]:
    for s in scalars:
        if str(s.get("name","")) in names:
            try: return float(s.get("value"))
            except:
                v = to_float(s.get("value"))
                if v is not None: return v
    return None

def infer_sf(label: str, parameters: List[dict]) -> Optional[int]:
    m = re.search(r"sf[_-]?(\d+)", label, re.I)
    if m: return int(m.group(1))
    for p in parameters:
        if re.search(r"initialLoRaSF|finalSF", str(p.get("name","")), re.I):
            v = to_float(p.get("value"))
            if v is not None: return int(v)
    return None

# -------------------------
# Analyze one bundle
# -------------------------
def analyze_one(label: str, bundle: Dict[str, Path], print_positions: bool) -> Dict[str, Any]:
    print(f"\n=== ANALYZING: {label} ===")
    for file_type, path in bundle.items():
        print(f"  Reading {file_type}: {path.name}")

    params  = list_in(read_json(bundle["parameters"]), "parameters")
    scalars = list_in(read_json(bundle["scalars"]), "scalars")

    # Basic config
    nodes_val = None
    interval_s = None
    sim_min = None
    for p in params:
        nm = str(p.get("name",""))
        if re.fullmatch(r"numberOfNodes", nm, re.I):
            nodes_val = int(to_float(p.get("value")) or 0)
        elif re.fullmatch(r"(timeToNextPacket|sendInterval)", nm, re.I):
            interval_s = parse_time_seconds(p.get("value")) or interval_s
        elif re.fullmatch(r"(sim-time-limit|simulated time)", nm, re.I):
            s = parse_time_seconds(p.get("value"))
            if s is not None:
                sim_min = s/60.0

    sf = infer_sf(label, params)

    # Totals (robust)
    sent_by_node = sent_by_node_from_scalars(scalars)
    recv_by_node = recv_by_node_from_scalars(scalars)

    sent_candidates: List[int] = []
    if sent_by_node:
        sent_candidates.append(sum(sent_by_node.values()))
    for name in ("LoRa_AppPacketSent:count", "LoRaTransmissionCreated:count", "txPk:count"):
        v = pick_scalar(scalars, [name])
        if v is not None:
            sent_candidates.append(int(v))
    sent_total = max(sent_candidates) if sent_candidates else 0

    recv_candidates: List[int] = []
    if recv_by_node:
        recv_candidates.append(int(sum(recv_by_node.values())))
    for name in ("LoRa_ServerPacketReceived:count", "totalReceivedPackets"):
        v = pick_scalar(scalars, [name])
        if v is not None:
            recv_candidates.append(int(v))
    v_rxok = pick_scalar(scalars, ["LoRaGWRadioReceptionFinishedCorrect:count"])
    if v_rxok is not None:
        recv_candidates.append(int(v_rxok))
    recv_total = max(recv_candidates) if recv_candidates else 0

    if (not sent_by_node) and nodes_val and sent_total:
        msgs_per_node = int(round(sent_total / float(nodes_val)))
        sent_by_node = {n: msgs_per_node for n in range(nodes_val)}

    if sent_total < recv_total:
        sent_total = recv_total

    collisions = pick_scalar(scalars, ["LoRaReceptionCollision:count"])
    undersens  = pick_scalar(scalars, ["rcvBelowSensitivity"])
    rx_util    = pick_scalar(scalars, ["rx channel utilization (%)"])
    rx_idle    = pick_scalar(scalars, ["rx channel idle (%)"])

    dropped = max(0, int(sent_total) - int(recv_total))
    pdr = (100.0 * recv_total / sent_total) if sent_total else 0.0
    if pdr > 100.0: pdr = 100.0

    # Positions & capture
    node_pos = extract_node_positions(params, scalars)     # {node: (x,y)}
    gw_xy    = extract_gateway_xy(params, scalars)         # (x,y) or None

    if print_positions:
        print(f"\n[{label}] POSITIONS DEBUG")
        if gw_xy:
            print(f"  GW[0]: ({gw_xy[0]}, {gw_xy[1]})")
        else:
            print("  GW[0]: NOT FOUND")
        if node_pos:
            for n in sorted(node_pos):
                x,y = node_pos[n]
                print(f"  Node[{n}]: ({x}, {y})")
        else:
            print("  Nodes: NONE FOUND")

    near_pdr = far_pdr = cap_delta = None
    if gw_xy and node_pos and sent_by_node:
        gx, gy = gw_xy
        nodes_present = [n for n in node_pos.keys() if n in sent_by_node]
        if nodes_present:
            d = {n: math.hypot(node_pos[n][0]-gx, node_pos[n][1]-gy) for n in nodes_present}
            ds = sorted(d[n] for n in nodes_present)
            q1 = ds[len(ds)//4]
            q3 = ds[(3*len(ds))//4]
            near = [n for n in nodes_present if d[n] <= q1]
            far  = [n for n in nodes_present if d[n] >= q3]

            def mean_pdr(ns: List[int]) -> Optional[float]:
                vals=[]
                for i in ns:
                    s = sent_by_node.get(i,0); r = recv_by_node.get(i,0)
                    if s>0: vals.append(100.0*r/s)
                return sum(vals)/len(vals) if vals else None

            near_pdr = mean_pdr(near)
            far_pdr  = mean_pdr(far)
            if near_pdr is not None and far_pdr is not None:
                cap_delta = near_pdr - far_pdr

    # Estimate Sim(min) if missing
    if sim_min is None and nodes_val and interval_s and sent_total:
        sim_min = (sent_total / float(nodes_val)) * (interval_s/60.0)

    return {
        "Configuration": label,
        "SF": sf,
        "Nodes": nodes_val or (len(sent_by_node) if sent_by_node else None),
        "Int(s)": interval_s,
        "Sim(min)": sim_min,
        "Sent": int(sent_total or 0),
        "Recv": int(recv_total or 0),
        "Drop": int(dropped),
        "PDR(%)": pdr,
        "NearPDR(%)": near_pdr,
        "FarPDR(%)":  far_pdr,
        "CaptureΔ(%)": cap_delta,
        "RxOk": int(v_rxok) if v_rxok is not None else None,
        "Collisions": int(collisions) if collisions is not None else None,
        "UnderSens": int(undersens) if undersens is not None else None,
        "RxUtil(%)": rx_util,
        "RxIdle(%)": rx_idle,
    }

# -------------------------
# Printing
# -------------------------
def fmt(x, d=2):
    if x is None: return "NA"
    if isinstance(x, int): return f"{x:d}"
    try: return f"{float(x):.{d}f}"
    except: return str(x)

def print_scoreboard(rows: List[Dict[str, Any]], area: Optional[str]):
    title = "OMNeT++ FLoRa — Scenario 06 (Collision / Capture) — SCOREBOARD"
    if area:
        title += f"  (area: {area})"
    print("\n" + "="*120)
    print(title)
    print("="*120)
    header = ("Config","SF","Nodes","Int(s)","Sim(min)","Sent","Recv","Drop","PDR(%)",
              "NearPDR(%)","FarPDR(%)","CaptureΔ(%)","RxOk","Collisions","UnderSens","RxUtil(%)","RxIdle(%)")
    fmtrow = "{:<45} {:>2} {:>5} {:>7} {:>8} {:>6} {:>6} {:>6} {:>7} {:>10} {:>10} {:>11} {:>5} {:>10} {:>10} {:>9} {:>8}"
    print(fmtrow.format(*header))
    for r in rows:
        print(fmtrow.format(
            r.get("Configuration",""),
            fmt(r.get("SF"),0),
            fmt(r.get("Nodes"),0),
            fmt(r.get("Int(s)"),0),
            fmt(r.get("Sim(min)"),1),
            fmt(r.get("Sent"),0),
            fmt(r.get("Recv"),0),
            fmt(r.get("Drop"),0),
            fmt(r.get("PDR(%)"),2),
            fmt(r.get("NearPDR(%)"),2),
            fmt(r.get("FarPDR(%)"),2),
            fmt(r.get("CaptureΔ(%)"),2),
            fmt(r.get("RxOk"),0),
            fmt(r.get("Collisions"),0),
            fmt(r.get("UnderSens"),0),
            fmt(r.get("RxUtil(%)"),2),
            fmt(r.get("RxIdle(%)"),2),
        ))
    print("="*120)

# -------------------------
# Main
# -------------------------
def main():
    ap = argparse.ArgumentParser(description="Analyze OMNeT++/FLoRa Scenario 06 (Collision / Capture) — area-aware")
    ap.add_argument("--json-dir", type=Path, default=Path("json_exports"))
    ap.add_argument("--area", type=str, default=None,
                    help="Area suffix to filter files by (e.g. 1x1km, 2x2km). Also accepts alias _1km etc.")
    ap.add_argument("--print-positions", action="store_true", help="Print all GW and node positions per run")
    args = ap.parse_args()

    if not args.json_dir.exists():
        print(f"[error] JSON dir not found: {args.json_dir}"); return

    bundles = find_bundles(args.json_dir, args.area)
    if not bundles:
        print("[warn] No scenario-06 collision bundles found for requested area." if args.area
              else "[warn] No scenario-06 collision bundles found.")
        return

    rows = []
    for label, bundle in bundles:
        rows.append(analyze_one(label, bundle, print_positions=args.print_positions))

    print_scoreboard(rows, args.area)

if __name__ == "__main__":
    main()
