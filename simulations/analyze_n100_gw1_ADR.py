#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Analyzer for OMNeT++ FLoRa scenario: n100-gw1-ADR
- Reads either merged *_extracted.json or the four raw JSONs.
- Computes totals, PDR, radio pipeline (collisions/captures), ADR activity, energy (if available).
- Extracts per-node init/final SF and TP if present.
- Saves CSV (summary, per-node) and JSON (detailed blobs).

Usage:
  python analyze_n100_gw1_ADR.py --json-dir json_exports --base n100-gw1-ADR --out-prefix n100-gw1-ADR
"""

from __future__ import annotations
import argparse
import json
import math
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from collections import defaultdict, Counter

import pandas as pd

# ------------------------ utilities ------------------------

def deep_iter(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from deep_iter(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from deep_iter(v)

TIME_UNITS = {"s": 1, "sec": 1, "ms": 1e-3, "us": 1e-6, "min": 60, "h": 3600, "day": 86400, "d": 86400}

def parse_time_to_seconds(val: Optional[str]) -> Optional[float]:
    if val is None:
        return None
    s = str(val).strip()
    # pure number (assume seconds)
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return float(s)
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([A-Za-z]+)\s*", s)
    if not m:
        return None
    num, unit = m.group(1), m.group(2).lower()
    return float(num) * TIME_UNITS.get(unit, float("nan"))

# ------------------------ bundle loader --------------------

def load_bundle(json_dir: Path, base: str) -> Optional[Dict[str, Any]]:
    """Return a dict with either merged or raw sections for the given base (without suffix)."""
    merged = json_dir / f"{base}_extracted.json"
    if merged.exists():
        with merged.open("r") as f:
            return json.load(f)
    need = {
        "parameters": json_dir / f"{base}_parameters.json",
        "scalars":    json_dir / f"{base}_scalars.json",
        "vectors":    json_dir / f"{base}_app_vectors.json",
        "histograms": json_dir / f"{base}_histograms.json",
    }
    if all(p.exists() for p in need.values()):
        return {k: json.load(open(p, "r")) for k, p in need.items()}
    return None

def get_section(bundle: Dict[str, Any], name: str) -> Dict[str, Any]:
    if "extracted_data" in bundle and name in bundle["extracted_data"]:
        return bundle["extracted_data"][name]
    return bundle.get(name, {})

# --------------------- parameter/scalar access ----------------------------

def find_param(parameters_section: Dict[str, Any], name_regex: str, module_regex: Optional[str] = None) -> Optional[str]:
    name_re = re.compile(name_regex)
    module_re = re.compile(module_regex) if module_regex else None
    for d in deep_iter(parameters_section):
        if isinstance(d, dict) and "name" in d and "value" in d:
            nm = str(d.get("name",""))
            md = str(d.get("module",""))
            if name_re.search(nm) and (module_re is None or module_re.search(md)):
                return d.get("value")
    return None

def find_all_params(parameters_section: Dict[str, Any], name_regex: str, module_regex: Optional[str] = None) -> List[Dict[str, Any]]:
    out = []
    name_re = re.compile(name_regex)
    module_re = re.compile(module_regex) if module_regex else None
    for d in deep_iter(parameters_section):
        if isinstance(d, dict) and "name" in d and "value" in d:
            nm = str(d.get("name",""))
            md = str(d.get("module",""))
            if name_re.search(nm) and (module_re is None or module_re.search(md)):
                out.append(d)
    return out

def read_server_scalar(scalars_section: Dict[str, Any], names: List[str]) -> Optional[float]:
    for d in deep_iter(scalars_section):
        if isinstance(d, dict) and all(k in d for k in ("module","name","value")):
            if str(d["module"]).endswith("networkServer.app[0]") and d["name"] in names:
                try:
                    return float(d["value"])
                except Exception:
                    pass
    return None

def sum_node_scalar(scalars_section: Dict[str, Any], name: str, module_tail: str = ".loRaNodes[") -> Optional[float]:
    total, found = 0.0, False
    for d in deep_iter(scalars_section):
        if isinstance(d, dict) and all(k in d for k in ("module","name","value")):
            mod = str(d["module"])
            if module_tail in mod and d["name"] == name:
                try:
                    total += float(d["value"])
                    found = True
                except Exception:
                    pass
    return total if found else None

def sum_scalar_glob(scalars_section: Dict[str, Any], names: List[str]) -> Dict[str, float]:
    sums = defaultdict(float)
    seen = defaultdict(bool)
    for d in deep_iter(scalars_section):
        if isinstance(d, dict) and "name" in d and "value" in d:
            nm = str(d["name"])
            if nm in names:
                try:
                    sums[nm] += float(d["value"])
                    seen[nm] = True
                except Exception:
                    pass
    return {k: (sums[k] if seen[k] else 0.0) for k in names}

# --------------------- vector helpers ------------------------------------

def iter_vectors(vectors_section: Dict[str, Any]):
    """Yield (module, name, values) for each vector found (values are numeric Y’s)."""
    for d in deep_iter(vectors_section):
        if not isinstance(d, dict): 
            continue
        if "module" in d and "name" in d:
            vals = None
            if "values" in d and isinstance(d["values"], list) and d["values"] and isinstance(d["values"][0], (list,tuple)):
                try:
                    vals = [float(x[1]) for x in d["values"] if len(x)>=2]
                except Exception:
                    pass
            elif "y" in d and isinstance(d["y"], list):
                try:
                    vals = [float(y) for y in d["y"]]
                except Exception:
                    pass
            elif "value" in d and isinstance(d["value"], list):
                try:
                    vals = [float(y) for y in d["value"]]
                except Exception:
                    pass
            if vals is not None and len(vals)>0:
                yield str(d["module"]), str(d["name"]), vals

def last_value(values: List[float]) -> Optional[float]:
    return values[-1] if values else None

# --------------------- extraction logic ----------------------------------

def detect_nodes_count(bundle: Dict[str, Any]) -> Optional[int]:
    params = get_section(bundle, "parameters")
    v = find_param(params, r"numberOfNodes", r"LoRaNetworkTest")
    try:
        return int(float(v)) if v is not None else None
    except Exception:
        return None

def detect_sim_seconds(bundle: Dict[str, Any]) -> Optional[float]:
    params = get_section(bundle, "parameters")
    lim = find_param(params, r"sim-time-limit", r"^LoRaNetworkTest$")
    return parse_time_to_seconds(lim) if lim else None

def detect_packet_interval(bundle: Dict[str, Any]) -> Optional[float]:
    params = get_section(bundle, "parameters")
    # SimpleLoRaApp naming varies; cover common names
    v = find_param(params, r"(timeToNextPacket|sendInterval)", r"\.app\[0\]|SimpleLoRaApp")
    if v is None:
        return None
    # Could be "exponential(100s)" — extract mean if present
    m = re.search(r"exponential\(\s*([\d\.]+)\s*([A-Za-z]+)\s*\)", str(v))
    if m:
        mean = float(m.group(1))
        unit = m.group(2)
        return mean * TIME_UNITS.get(unit.lower(), 1)
    return parse_time_to_seconds(str(v))

def detect_adr_flag(bundle: Dict[str, Any]) -> Optional[bool]:
    params = get_section(bundle, "parameters")
    v = find_param(params, r"evaluateADRinServer", r"networkServer")
    if v is None: 
        return None
    return str(v).strip().lower() in ("true","1","yes","on")

def read_totals(bundle: Dict[str, Any]) -> Tuple[Optional[int], Optional[int]]:
    scal = get_section(bundle, "scalars")
    sent = sum_node_scalar(scal, "sentPackets")
    rec  = read_server_scalar(scal, ["totalReceivedPackets","LoRa_ServerPacketReceived:count"])
    return (int(sent) if sent is not None else None,
            int(rec) if rec is not None else None)

def read_pipeline_stats(bundle: Dict[str, Any]) -> Dict[str, int]:
    scal = get_section(bundle, "scalars")
    names = [
        "LoRaGWRadioReceptionStarted:count",
        "LoRaGWRadioReceptionFinishedCorrect:count",
        "LoRaReceptionCollision:count",
        "LoRaReceptionCapture:count",
        "LoRa_GWPacketReceived:count",
    ]
    sums = sum_scalar_glob(scal, names)
    return {k: int(v) for k, v in sums.items()}

def read_energy_totals(bundle: Dict[str, Any]) -> Dict[str, float]:
    scal = get_section(bundle, "scalars")
    candidates = ["energyConsumedJ","totalEnergyConsumedJ","txEnergyJ","rxEnergyJ","sleepEnergyJ","idleEnergyJ"]
    sums = sum_scalar_glob(scal, candidates)
    return {k: float(v) for k, v in sums.items() if v>0.0}

def collect_sf_tp_distributions(bundle: Dict[str, Any]) -> Tuple[Counter, Counter]:
    """Return final SF and final TP distributions from vectors (best effort)."""
    vectors = get_section(bundle, "vectors")
    sf_name_res = [re.compile(r"(?:SF|SpreadingFactor|LoRaSF|currentSF)", re.I)]
    tp_name_res = [re.compile(r"(?:TP|TxPower|currentTP|LoRaTP)", re.I)]
    sf_final = Counter()
    tp_final = Counter()
    seen_node_sf = {}
    seen_node_tp = {}

    for module, name, values in iter_vectors(vectors):
        if ".loRaNodes[" not in module:
            continue
        node_m = re.search(r"\.loRaNodes\[(\d+)\]", module)
        node_id = int(node_m.group(1)) if node_m else None
        if node_id is None:
            continue
        lv = last_value(values)
        if lv is None:
            continue
        if any(rx.search(name) for rx in sf_name_res):
            try: seen_node_sf[node_id] = int(round(lv))
            except Exception: pass
        if any(rx.search(name) for rx in tp_name_res):
            try: seen_node_tp[node_id] = int(round(lv))
            except Exception: pass

    for sf in seen_node_sf.values():
        sf_final[sf] += 1
    for tp in seen_node_tp.values():
        tp_final[tp] += 1

    return sf_final, tp_final

def build_per_node_table(bundle: Dict[str, Any]) -> pd.DataFrame:
    scal = get_section(bundle, "scalars")
    params = get_section(bundle, "parameters")
    vectors = get_section(bundle, "vectors")

    per = defaultdict(dict)

    # sentPackets & energy
    for d in deep_iter(scal):
        if not isinstance(d, dict): continue
        if "module" in d and "name" in d and "value" in d:
            mod, nm, val = str(d["module"]), str(d["name"]), d["value"]
            m = re.search(r"\.loRaNodes\[(\d+)\]", mod)
            if not m: continue
            nid = int(m.group(1))
            if nm == "sentPackets":
                try: per[nid]["Sent"] = int(float(val))
                except Exception: pass
            if nm in ("energyConsumedJ","txEnergyJ","rxEnergyJ","sleepEnergyJ","idleEnergyJ"):
                try: per[nid][nm] = float(val)
                except Exception: pass

    # initial SF/TP (if parameters export per-node)
    for p in find_all_params(params, r"initialLoRaSF", r"\.loRaNodes\[(\d+)\]\.app\[0\]"):
        m = re.search(r"\.loRaNodes\[(\d+)\]", str(p.get("module","")))
        if not m: continue
        nid = int(m.group(1))
        try: per[nid]["InitSF"] = int(float(p["value"]))
        except Exception: pass

    for p in find_all_params(params, r"initialLoRaTP", r"\.loRaNodes\[(\d+)\]\.app\[0\]"):
        m = re.search(r"\.loRaNodes\[(\d+)\]", str(p.get("module","")))
        if not m: continue
        nid = int(m.group(1))
        try:
            v = str(p["value"]).replace("dBm","").strip()
            per[nid]["InitTP_dBm"] = float(v)
        except Exception:
            pass

    # final SF/TP (vectors)
    sf_name_res = [re.compile(r"(?:SF|SpreadingFactor|LoRaSF|currentSF)", re.I)]
    tp_name_res = [re.compile(r"(?:TP|TxPower|currentTP|LoRaTP)", re.I)]
    last_sf, last_tp = {}, {}

    for module, name, values in iter_vectors(vectors):
        m = re.search(r"\.loRaNodes\[(\d+)\]", module)
        if not m: continue
        nid = int(m.group(1))
        lv = last_value(values)
        if lv is None: continue
        if any(rx.search(name) for rx in sf_name_res):
            try: last_sf[nid] = int(round(lv))
            except Exception: pass
        if any(rx.search(name) for rx in tp_name_res):
            try: last_tp[nid] = float(lv)
            except Exception: pass

    for nid, sf in last_sf.items():
        per[nid]["FinalSF"] = sf
    for nid, tp in last_tp.items():
        per[nid]["FinalTP_dBm"] = tp

    if not per:
        return pd.DataFrame()

    df = pd.DataFrame.from_dict(per, orient="index").reset_index().rename(columns={"index":"NodeID"})
    cols = ["NodeID","Sent","InitSF","FinalSF","InitTP_dBm","FinalTP_dBm","energyConsumedJ","txEnergyJ","rxEnergyJ","sleepEnergyJ","idleEnergyJ"]
    for c in cols:
        if c not in df.columns:
            df[c] = pd.NA
    return df[cols]

# --------------------- main analysis -------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Analyze FLoRa n100-gw1-ADR scenario from JSON exports")
    ap.add_argument("--json-dir", type=Path, default=Path("json_exports"), help="Folder with exported JSON files")
    ap.add_argument("--base", default="n100-gw1-ADR", help="Base file name without suffix (e.g., 'n100-gw1-ADR')")
    ap.add_argument("--out-prefix", type=Path, default=Path("n100-gw1-ADR"), help="Output file prefix")
    args = ap.parse_args()

    jd = args.json_dir
    base = args.base

    # Auto-pick the newest run (e.g., -s0 / -s1)
    candidates = sorted(jd.glob(f"{base}-s*_scalars.json"))
    if candidates:
        # use the newest (lexicographically often not newest by time; pick by mtime)
        newest = max(candidates, key=lambda p: p.stat().st_mtime)
        base_no_suffix = re.sub(r"_scalars\.json$", "", newest.name)
    else:
        # fallback to bare base files
        base_no_suffix = base

    bundle = load_bundle(jd, base_no_suffix)
    if not bundle:
        print(f"❌ Could not find JSON bundle for base '{base_no_suffix}' in {jd}")
        return

    params = get_section(bundle, "parameters")
    scalars = get_section(bundle, "scalars")

    # Basics
    n_nodes = detect_nodes_count(bundle)
    sim_sec = detect_sim_seconds(bundle)
    interval_sec = detect_packet_interval(bundle)
    adr_enabled = detect_adr_flag(bundle)

    total_sent, total_received = read_totals(bundle)
    pipeline = read_pipeline_stats(bundle)
    energy = read_energy_totals(bundle)
    sf_final, tp_final = collect_sf_tp_distributions(bundle)
    per_node = build_per_node_table(bundle)

    # ADR activity
    adr_sums = sum_scalar_glob(scalars, ["TotalADRChanges","ADRChanges","NodesWithADRChanges"])
    adr_changes = int(adr_sums.get("TotalADRChanges") or adr_sums.get("ADRChanges") or 0)
    adr_nodes_changed = int(adr_sums.get("NodesWithADRChanges") or 0)

    pdr = (100.0 * total_received / total_sent) if (total_sent and total_received is not None and total_sent>0) else None
    per_node_sent = (total_sent / n_nodes) if (total_sent and n_nodes) else None
    recv_per_hour = (total_received / (sim_sec/3600.0)) if (total_received is not None and sim_sec and sim_sec>0) else None

    # Print compact summary
    print("\n==================== n100-gw1-ADR — Summary ====================")
    print(f"JSON dir             : {jd}")
    print(f"Base                 : {base_no_suffix}")
    print(f"Nodes                : {n_nodes}")
    print(f"Sim time (s)         : {sim_sec}")
    print(f"Send interval (mean) : {interval_sec} s")
    print(f"ADR enabled          : {adr_enabled}")
    print("---------------------------------------------------------------")
    print(f"Total sent           : {total_sent}")
    print(f"Total received       : {total_received}")
    print(f"PDR (%)              : {None if pdr is None else round(pdr,4)}")
    print(f"Per-node sent (avg)  : {per_node_sent}")
    print(f"Received per hour    : {recv_per_hour}")
    print("---------------------------------------------------------------")
    print(f"GW RX Started        : {pipeline.get('LoRaGWRadioReceptionStarted:count', 0)}")
    print(f"GW RX OK             : {pipeline.get('LoRaGWRadioReceptionFinishedCorrect:count', 0)}")
    print(f"Collisions           : {pipeline.get('LoRaReceptionCollision:count', 0)}")
    print(f"Captures             : {pipeline.get('LoRaReceptionCapture:count', 0)}")
    print(f"GW Packets Received  : {pipeline.get('LoRa_GWPacketReceived:count', 0)}")
    print("---------------------------------------------------------------")
    if energy:
        print("Energy (totals over nodes):")
        for k,v in energy.items():
            print(f"  - {k}: {v}")
    else:
        print("Energy totals        : (not exported)")
    print("---------------------------------------------------------------")
    if sf_final:
        print("Final SF distribution:")
        for sf,count in sorted(sf_final.items()):
            print(f"  - SF{sf}: {count}")
    else:
        print("Final SF distribution: (not available)")
    if tp_final:
        print("Final TP distribution (dBm):")
        for tp,count in sorted(tp_final.items()):
            print(f"  - {tp} dBm: {count}")
    else:
        print("Final TP distribution: (not available)")
    print("---------------------------------------------------------------")
    print(f"ADR changes (total)  : {adr_changes}")
    print(f"Nodes with ADR change: {adr_nodes_changed}")
    print("================================================================\n")

    # Save summary CSV
    def _out(base: Path, tail: str) -> Path:
        return base.parent / (base.name + tail)

    row = {
        "Nodes": n_nodes,
        "SimSeconds": sim_sec,
        "IntervalMean_s": interval_sec,
        "ADR_Enabled": adr_enabled,
        "TotalSent": total_sent,
        "TotalReceived": total_received,
        "PDR_percent": None if pdr is None else round(pdr,4),
        "GW_RX_Started": pipeline.get("LoRaGWRadioReceptionStarted:count", 0),
        "GW_RX_OK": pipeline.get("LoRaGWRadioReceptionFinishedCorrect:count", 0),
        "Collisions": pipeline.get("LoRaReceptionCollision:count", 0),
        "Captures": pipeline.get("LoRaReceptionCapture:count", 0),
        "GW_Packets_Received": pipeline.get("LoRa_GWPacketReceived:count", 0),
        "ADR_Changes_Total": adr_changes,
        "ADR_NodesWithChanges": adr_nodes_changed,
    }
    summary_df = pd.DataFrame([row])
    out_summary = _out(args.out_prefix, "_summary.csv")
    summary_df.to_csv(out_summary, index=False)
    print(f"💾 Summary CSV: {out_summary}")

    # Save per-node CSV (if any)
    if isinstance(per_node, pd.DataFrame) and not per_node.empty:
        out_pn = _out(args.out_prefix, "_per_node.csv")
        per_node.to_csv(out_pn, index=False)
        print(f"💾 Per-node CSV: {out_pn}")
    else:
        print("ℹ️  Per-node table not available in exports.")

    # Save details JSON
    details = {
        "base": base_no_suffix,
        "nodes": n_nodes,
        "sim_seconds": sim_sec,
        "interval_mean_s": interval_sec,
        "adr_enabled": adr_enabled,
        "totals": {
            "sent": total_sent,
            "received": total_received,
            "pdr_percent": None if pdr is None else round(pdr,4),
            "recv_per_hour": recv_per_hour,
        },
        "radio_pipeline": pipeline,
        "energy_totals": energy or {},
        "final_distributions": {
            "sf": dict(sorted(sf_final.items())),
            "tp_dbm": dict(sorted(tp_final.items())),
        }
    }
    out_json = _out(args.out_prefix, "_details.json")
    out_json.write_text(json.dumps(details, indent=2))
    print(f"💾 Details JSON: {out_json}")

if __name__ == "__main__":
    main()
