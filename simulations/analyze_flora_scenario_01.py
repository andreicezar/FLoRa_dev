#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OMNeT++ FLoRa — Scenario 01 Deep Analyzer
-----------------------------------------
Reads either:
  - merged: scenario-01-baseline-*-s0_extracted.json
  - raw:    scenario-01-baseline-*-s0_{scalars,parameters,app_vectors,histograms}.json

Outputs:
  - scenario_01_flora_summary.csv         (one row per sub-scenario; rich metrics)
  - scenario_01_flora_per_node.csv        (per-node KPIs when present)
  - scenario_01_flora_details.json        (structured details per sub-scenario: distributions, energy, radio stats)
  - scenario_01_flora_analysis.png        (optional compact figure if data available)

It is intentionally robust:
  * understands merged (under "extracted_data") and raw layouts
  * searches multiple possible scalar/vector names
  * tolerates missing metrics and still produces best-effort results
"""

from __future__ import annotations
import argparse
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd
import matplotlib.pyplot as plt

# --------------------- helpers: time parsing, walking ---------------------

TIME_UNITS = {"s": 1, "sec": 1, "ms": 1e-3, "us": 1e-6, "min": 60, "h": 3600}

def parse_time_to_seconds(val: Optional[str]) -> Optional[float]:
    if val is None:
        return None
    s = str(val).strip()
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return float(s)
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([A-Za-z]+)\s*", s)
    if not m:
        return None
    num, unit = m.group(1), m.group(2).lower()
    return float(num) * TIME_UNITS.get(unit, float("nan"))

def deep_iter(obj: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from deep_iter(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from deep_iter(v)

# --------------------- bundle access (merged/raw) -------------------------

def load_bundle(base_no_suffix: str, json_dir: Path) -> Optional[Dict[str, Any]]:
    """Return a unified dict representing this sub-scenario."""
    merged = json_dir / f"{base_no_suffix}_extracted.json"
    if merged.exists():
        with open(merged, "r") as f:
            return json.load(f)

    need = {
        "parameters": json_dir / f"{base_no_suffix}_parameters.json",
        "scalars":    json_dir / f"{base_no_suffix}_scalars.json",
        "vectors":    json_dir / f"{base_no_suffix}_app_vectors.json",
        "histograms": json_dir / f"{base_no_suffix}_histograms.json",
    }
    for p in need.values():
        if not p.exists():
            return None
    return {k: json.load(open(p, "r")) for k, p in need.items()}

def get_section(bundle: Dict[str, Any], name: str) -> Dict[str, Any]:
    """Return 'scalars'|'parameters'|'vectors'|'histograms' section, robust to merged/raw layouts."""
    if "extracted_data" in bundle and name in bundle["extracted_data"]:
        return bundle["extracted_data"][name]
    return bundle.get(name, {})

# --------------------- lookups: parameters & scalars ----------------------

def find_param(parameters_section: Dict[str, Any], name_regex: str, module_regex: Optional[str] = None) -> Optional[str]:
    name_re = re.compile(name_regex)
    module_re = re.compile(module_regex) if module_regex else None
    for d in deep_iter(parameters_section):
        if not isinstance(d, dict):
            continue
        if "name" in d and "value" in d:
            if name_re.search(str(d.get("name", ""))) and (module_re is None or module_re.search(str(d.get("module", "")))):
                return d.get("value")
    return None

def find_all_params(parameters_section: Dict[str, Any], name_regex: str, module_regex: Optional[str] = None) -> List[Dict[str, Any]]:
    out = []
    name_re = re.compile(name_regex)
    module_re = re.compile(module_regex) if module_regex else None
    for d in deep_iter(parameters_section):
        if isinstance(d, dict) and "name" in d and "value" in d:
            if name_re.search(str(d.get("name", ""))) and (module_re is None or module_re.search(str(d.get("module", "")))):
                out.append(d)
    return out

def read_server_scalar(scalars_section: Dict[str, Any], names: List[str]) -> Optional[float]:
    for d in deep_iter(scalars_section):
        if isinstance(d, dict) and all(k in d for k in ("module", "name", "value")):
            if str(d["module"]).endswith("networkServer.app[0]") and d["name"] in names:
                try:
                    return float(d["value"])
                except Exception:
                    pass
    return None

def sum_node_scalar(scalars_section: Dict[str, Any], name: str, module_tail: str = ".loRaNodes[") -> Optional[float]:
    total, found = 0.0, False
    for d in deep_iter(scalars_section):
        if isinstance(d, dict) and all(k in d for k in ("module", "name", "value")):
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

# --------------------- vectors: discovery & reductions --------------------

def iter_vectors(vectors_section: Dict[str, Any]):
    """
    Generator that yields (module, name, values) for every vector found.
    Supports common merged/raw shapes.
    values: list of numeric samples (time is ignored for aggregations here)
    """
    # merged extractor often stores arrays under fields like "vectors" or nested
    for d in deep_iter(vectors_section):
        if not isinstance(d, dict):
            continue
        if "module" in d and "name" in d:
            # seen formats: {"module": "...", "name": "...", "values": [[t,v],...]} or {"x":[], "y":[]}
            vals = None
            if "values" in d and isinstance(d["values"], list) and d["values"] and isinstance(d["values"][0], (list, tuple)):
                try:
                    vals = [float(x[1]) for x in d["values"] if len(x) >= 2]
                except Exception:
                    pass
            elif "y" in d and isinstance(d["y"], list):
                try:
                    vals = [float(y) for y in d["y"]]
                except Exception:
                    pass
            elif "value" in d and isinstance(d["value"], list):  # rare
                try:
                    vals = [float(y) for y in d["value"]]
                except Exception:
                    pass
            if vals is not None and len(vals) > 0:
                yield str(d["module"]), str(d["name"]), vals

def last_value(values: List[float]) -> Optional[float]:
    return values[-1] if values else None

def avg_value(values: List[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None

# --------------------- dataclasses for tidy aggregation -------------------

@dataclass
class ScenarioDetails:
    name: str
    init_sf: Optional[int] = None
    init_tp_dbm: Optional[float] = None
    adr_enabled: Optional[bool] = None
    n_nodes: Optional[int] = None
    sim_seconds: Optional[float] = None

    total_sent: Optional[int] = None
    total_received: Optional[int] = None
    pdr_percent: Optional[float] = None

    # radio pipeline
    gw_rx_started: Optional[int] = None
    gw_rx_ok: Optional[int] = None
    collisions: Optional[int] = None
    captures: Optional[int] = None

    # energy (totals over nodes)
    energy_total_j: Optional[float] = None
    energy_tx_j: Optional[float] = None
    energy_rx_j: Optional[float] = None
    energy_sleep_j: Optional[float] = None

    # distributions
    sf_initial_dist: Dict[int, int] = field(default_factory=dict)
    sf_final_dist: Dict[int, int] = field(default_factory=dict)
    tp_initial_dist: Dict[int, int] = field(default_factory=dict)
    tp_final_dist: Dict[int, int] = field(default_factory=dict)

    # ADR activity
    adr_changes_total: Optional[int] = None
    nodes_with_adr_changes: Optional[int] = None

    # misc
    channel_util_percent: Optional[float] = None
    theoretical_toa_ms: Optional[float] = None
    total_airtime_ms: Optional[float] = None

# --------------------- extraction & derivation ----------------------------

def subscenario_name_from_base(base: str) -> str:
    m = re.search(r"scenario-01-[^-]+-(.+?)-s\d+$", base)
    return m.group(1) if m else base

def detect_nodes_count(bundle: Dict[str, Any]) -> Optional[int]:
    if "node_counts" in bundle and isinstance(bundle["node_counts"], dict):
        try:
            return int(bundle["node_counts"].get("end_node", 0)) or None
        except Exception:
            pass
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

def detect_adr_flag(bundle: Dict[str, Any], fallback_name: str) -> bool:
    params = get_section(bundle, "parameters")
    v = find_param(params, r"evaluateADRinServer", r"networkServer")
    if v is not None:
        return str(v).strip().lower() in ("true", "1", "yes", "on")
    return "adr" in fallback_name.lower()

def read_totals(bundle: Dict[str, Any]) -> Tuple[Optional[int], Optional[int]]:
    scal = get_section(bundle, "scalars")
    sent = sum_node_scalar(scal, "sentPackets")  # best source
    if sent is None:
        # compute from parameters as fallback
        params = get_section(bundle, "parameters")
        nodes = detect_nodes_count(bundle)
        tt = find_param(params, r"timeToNextPacket", r"\.app\[0\]$|SimpleLoRaApp")
        tf = find_param(params, r"timeToFirstPacket", r"\.app\[0\]$|SimpleLoRaApp")  # not used in count
        nps = find_param(params, r"numberOfPacketsToSend", r"\.app\[0\]$|SimpleLoRaApp")
        sim_s = detect_sim_seconds(bundle)
        int_s = parse_time_to_seconds(tt) if tt else None
        if nodes and sim_s and int_s and int_s > 0:
            per_node = int(sim_s // int_s)
            try:
                nps_i = int(float(nps)) if nps else 0
                if nps_i > 0:
                    per_node = min(per_node, nps_i)
            except Exception:
                pass
            sent = nodes * per_node
    rec = read_server_scalar(scal, ["totalReceivedPackets", "LoRa_ServerPacketReceived:count"])
    return (int(sent) if sent is not None else None,
            int(rec) if rec is not None else None)

def read_pipeline_stats(bundle: Dict[str, Any]) -> Dict[str, int]:
    scal = get_section(bundle, "scalars")
    names = [
        "LoRaGWRadioReceptionStarted:count",
        "LoRaGWRadioReceptionFinishedCorrect:count",
        "LoRaReceptionCollision:count",
        "LoRaReceptionCapture:count",  # if present
        "LoRa_GWPacketReceived:count",
    ]
    sums = sum_scalar_glob(scal, names)
    # make ints
    return {k: int(v) for k, v in sums.items()}

def read_energy_totals(bundle: Dict[str, Any]) -> Dict[str, float]:
    scal = get_section(bundle, "scalars")
    # common names in FLoRa energy models
    candidates = [
        "energyConsumedJ", "totalEnergyConsumedJ",
        "txEnergyJ", "rxEnergyJ", "sleepEnergyJ", "idleEnergyJ"
    ]
    sums = sum_scalar_glob(scal, candidates)
    # prefer specific channels if available
    return {k: float(v) for k, v in sums.items() if v > 0.0}

def collect_sf_tp_distributions(bundle: Dict[str, Any]) -> Tuple[Counter, Counter, Counter, Counter]:
    """
    Builds initial/final distributions for SF and TP.
    Initial: from parameters if present
    Final:   from vectors if present (last value per node), else fall back to scalars where available
    """
    params = get_section(bundle, "parameters")
    init_sf = Counter()
    init_tp = Counter()

    # initial SF/TP per node if exported per-node
    per_node_init_sf = find_all_params(params, r"initialLoRaSF", r"\.loRaNodes\[\d+\]\.app\[0\]")
    for p in per_node_init_sf:
        try:
            init_sf[int(float(p["value"]))] += 1
        except Exception:
            pass

    per_node_init_tp = find_all_params(params, r"initialLoRaTP", r"\.loRaNodes\[\d+\]\.app\[0\]")
    for p in per_node_init_tp:
        try:
            # TP often like "14 dBm" -> split number
            v = str(p["value"]).replace("dBm", "").strip()
            init_tp[int(round(float(v)))] += 1
        except Exception:
            pass

    # FINAL values from vectors (best effort: search common names)
    vectors = get_section(bundle, "vectors")
    sf_last_by_node = {}
    tp_last_by_node = {}

    # pattern candidates (module/name)
    sf_name_res = [re.compile(r"(?:SF|SpreadingFactor|LoRaSF|currentSF)", re.I)]
    tp_name_res = [re.compile(r"(?:TP|TxPower|currentTP|LoRaTP)", re.I)]

    for module, name, values in iter_vectors(vectors):
        if ".loRaNodes[" not in module:
            continue
        node_m = re.search(r"\.loRaNodes\[(\d+)\]", module)
        node_id = int(node_m.group(1)) if node_m else None
        if node_id is None:
            continue
        val_last = last_value(values)
        if val_last is None:
            continue

        # SF?
        if any(rx.search(name) for rx in sf_name_res):
            try:
                sf_last_by_node[node_id] = int(round(val_last))
            except Exception:
                pass
        # TP?
        if any(rx.search(name) for rx in tp_name_res):
            try:
                tp_last_by_node[node_id] = int(round(val_last))
            except Exception:
                pass

    final_sf = Counter(sf_last_by_node.values())
    final_tp = Counter(tp_last_by_node.values())
    return init_sf, final_sf, init_tp, final_tp

def read_adr_activity(bundle: Dict[str, Any]) -> Tuple[Optional[int], Optional[int]]:
    scal = get_section(bundle, "scalars")
    sums = sum_scalar_glob(scal, ["TotalADRChanges", "ADRChanges", "NodesWithADRChanges"])
    total_changes = int(sums.get("TotalADRChanges", 0) or sums.get("ADRChanges", 0))
    nodes_changed = int(sums.get("NodesWithADRChanges", 0))
    return (total_changes if total_changes > 0 else None,
            nodes_changed if nodes_changed > 0 else None)

def read_airtime_and_util(bundle: Dict[str, Any]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    scal = get_section(bundle, "scalars")
    # try scenario-wide
    tot_air_ms = read_server_scalar(scal, ["TotalAirTime_ms"])
    theo_toa = read_server_scalar(scal, ["TheoreticalToA_ms"])
    util = read_server_scalar(scal, ["ChannelUtilization_Percent"])
    # fallbacks: sum across nodes if above not present
    sums = sum_scalar_glob(scal, ["TotalAirTime_ms", "TheoreticalToA_ms", "ChannelUtilization_Percent"])
    tot_air_ms = tot_air_ms if tot_air_ms is not None else (sums.get("TotalAirTime_ms") or None)
    theo_toa = theo_toa if theo_toa is not None else (sums.get("TheoreticalToA_ms") or None)
    util = util if util is not None else (sums.get("ChannelUtilization_Percent") or None)
    return theo_toa, tot_air_ms, util

# --------------------- per-node table (best effort) -----------------------

def build_per_node_table(bundle: Dict[str, Any]) -> pd.DataFrame:
    scal = get_section(bundle, "scalars")
    params = get_section(bundle, "parameters")
    vectors = get_section(bundle, "vectors")

    # Sent/energy per node (scalars) — robust
    per_node = defaultdict(dict)

    for d in deep_iter(scal):
        if not isinstance(d, dict): continue
        if "module" in d and "name" in d and "value" in d:
            mod, nm, val = str(d["module"]), str(d["name"]), d["value"]
            node_m = re.search(r"\.loRaNodes\[(\d+)\]", mod)
            if not node_m: continue
            nid = int(node_m.group(1))
            if nm == "sentPackets":
                try: per_node[nid]["Sent"] = int(float(val))
                except Exception: pass
            # energy breakdowns
            if nm in ("energyConsumedJ", "txEnergyJ", "rxEnergyJ", "sleepEnergyJ", "idleEnergyJ"):
                try: per_node[nid][nm] = float(val)
                except Exception: pass

    # Initial SF/TP per node (parameters)
    for p in find_all_params(params, r"initialLoRaSF", r"\.loRaNodes\[(\d+)\]\.app\[0\]"):
        m = re.search(r"\.loRaNodes\[(\d+)\]", p.get("module",""))
        if not m: continue
        nid = int(m.group(1))
        try: per_node[nid]["InitSF"] = int(float(p["value"]))
        except Exception: pass

    for p in find_all_params(params, r"initialLoRaTP", r"\.loRaNodes\[(\d+)\]\.app\[0\]"):
        m = re.search(r"\.loRaNodes\[(\d+)\]", p.get("module",""))
        if not m: continue
        nid = int(m.group(1))
        try:
            v = str(p["value"]).replace("dBm","").strip()
            per_node[nid]["InitTP_dBm"] = float(v)
        except Exception:
            pass

    # Final SF/TP (vectors): last observed
    sf_name_res = [re.compile(r"(?:SF|SpreadingFactor|LoRaSF|currentSF)", re.I)]
    tp_name_res = [re.compile(r"(?:TP|TxPower|currentTP|LoRaTP)", re.I)]
    last_sf_by_node, last_tp_by_node = {}, {}

    for module, name, values in iter_vectors(vectors):
        node_m = re.search(r"\.loRaNodes\[(\d+)\]", module)
        if not node_m: continue
        nid = int(node_m.group(1))
        if any(rx.search(name) for rx in sf_name_res):
            lv = last_value(values)
            if lv is not None:
                try: last_sf_by_node[nid] = int(round(lv))
                except Exception: pass
        if any(rx.search(name) for rx in tp_name_res):
            lv = last_value(values)
            if lv is not None:
                try: last_tp_by_node[nid] = float(lv)
                except Exception: pass

    for nid, sf in last_sf_by_node.items():
        per_node[nid]["FinalSF"] = sf
    for nid, tp in last_tp_by_node.items():
        per_node[nid]["FinalTP_dBm"] = tp

    if not per_node:
        return pd.DataFrame()

    df = pd.DataFrame.from_dict(per_node, orient="index").reset_index().rename(columns={"index": "NodeID"})
    cols = ["NodeID","Sent","InitSF","FinalSF","InitTP_dBm","FinalTP_dBm","energyConsumedJ","txEnergyJ","rxEnergyJ","sleepEnergyJ","idleEnergyJ"]
    for c in cols:
        if c not in df.columns:
            df[c] = pd.NA
    return df[cols]

# --------------------- top-level analysis per sub-scenario ----------------

def analyze_subscenario(base: str, json_dir: Path) -> Optional[Tuple[ScenarioDetails, pd.DataFrame]]:
    bundle = load_bundle(base, json_dir)
    if not bundle:
        return None

    name = subscenario_name_from_base(base)
    params = get_section(bundle, "parameters")

    det = ScenarioDetails(name=name)
    det.adr_enabled = detect_adr_flag(bundle, name)
    det.n_nodes = detect_nodes_count(bundle)
    det.sim_seconds = detect_sim_seconds(bundle)

    # initial SF/TP *global* (if present)
    i_sf = find_param(params, r"initialLoRaSF", r"\.loRaNodes\[\d+\]\.app\[0\]")
    i_tp = find_param(params, r"initialLoRaTP", r"\.loRaNodes\[\d+\]\.app\[0\]")
    try:
        det.init_sf = int(float(i_sf)) if i_sf is not None else None
    except Exception:
        pass
    try:
        det.init_tp_dbm = float(str(i_tp).replace("dBm","").strip()) if i_tp is not None else None
    except Exception:
        pass

    # totals
    det.total_sent, det.total_received = read_totals(bundle)
    if det.total_sent and det.total_received is not None and det.total_sent > 0:
        det.pdr_percent = round(100.0 * det.total_received / det.total_sent, 4)

    # radio pipeline
    pipe = read_pipeline_stats(bundle)
    det.gw_rx_started = pipe.get("LoRaGWRadioReceptionStarted:count") or 0
    det.gw_rx_ok      = pipe.get("LoRaGWRadioReceptionFinishedCorrect:count") or 0
    det.collisions    = pipe.get("LoRaReceptionCollision:count") or 0
    det.captures      = pipe.get("LoRaReceptionCapture:count") or 0

    # energy totals
    en = read_energy_totals(bundle)
    det.energy_total_j = en.get("energyConsumedJ") or en.get("totalEnergyConsumedJ")
    det.energy_tx_j    = en.get("txEnergyJ")
    det.energy_rx_j    = en.get("rxEnergyJ")
    det.energy_sleep_j = en.get("sleepEnergyJ") or en.get("idleEnergyJ")

    # airtime & utilization
    det.theoretical_toa_ms, det.total_airtime_ms, det.channel_util_percent = read_airtime_and_util(bundle)

    # SF/TP distributions
    sf_i, sf_f, tp_i, tp_f = collect_sf_tp_distributions(bundle)
    det.sf_initial_dist = dict(sorted(sf_i.items()))
    det.sf_final_dist   = dict(sorted(sf_f.items()))
    det.tp_initial_dist = dict(sorted(tp_i.items()))
    det.tp_final_dist   = dict(sorted(tp_f.items()))

    # ADR activity
    det.adr_changes_total, det.nodes_with_adr_changes = read_adr_activity(bundle)

    # per-node table
    per_node_df = build_per_node_table(bundle)

    return det, per_node_df

# --------------------- export helpers ------------------------------------

def details_to_row(det: ScenarioDetails) -> Dict[str, Any]:
    row = {
        "Sub-Scenario": det.name,
        "Init SF": "Yes" if det.init_sf is not None else "No",
        "Init TP": "Yes" if det.init_tp_dbm is not None else "No",
        "ADR Enabled": "Yes" if det.adr_enabled else "No",
        "Total Sent": det.total_sent or 0,
        "Total Received": det.total_received or 0,
        "Overall PDR (%)": det.pdr_percent,
        "GW RX Started": det.gw_rx_started,
        "GW RX OK": det.gw_rx_ok,
        "Collisions": det.collisions,
        "Captures": det.captures,
        "Energy Total (J)": det.energy_total_j,
        "Energy TX (J)": det.energy_tx_j,
        "Energy RX (J)": det.energy_rx_j,
        "Energy Sleep/Idle (J)": det.energy_sleep_j,
        "Channel Utilization (%)": det.channel_util_percent,
        "Total Airtime (ms)": det.total_airtime_ms,
        "Theoretical ToA (ms)": det.theoretical_toa_ms,
        "ADR Changes": det.adr_changes_total,
        "Nodes With ADR Changes": det.nodes_with_adr_changes,
    }
    return row

def save_details_json(details_list: List[ScenarioDetails], out_path: Path):
    blob = {}
    for det in details_list:
        blob[det.name] = {
            "init": {
                "sf": det.init_sf,
                "tp_dbm": det.init_tp_dbm,
                "adr_enabled": det.adr_enabled,
                "n_nodes": det.n_nodes,
                "sim_seconds": det.sim_seconds,
            },
            "totals": {
                "sent": det.total_sent,
                "received": det.total_received,
                "pdr_percent": det.pdr_percent,
            },
            "radio_pipeline": {
                "gw_rx_started": det.gw_rx_started,
                "gw_rx_ok": det.gw_rx_ok,
                "collisions": det.collisions,
                "captures": det.captures,
            },
            "airtime": {
                "channel_util_percent": det.channel_util_percent,
                "total_airtime_ms": det.total_airtime_ms,
                "theoretical_toa_ms": det.theoretical_toa_ms,
            },
            "energy": {
                "total_j": det.energy_total_j,
                "tx_j": det.energy_tx_j,
                "rx_j": det.energy_rx_j,
                "sleep_or_idle_j": det.energy_sleep_j,
            },
            "distributions": {
                "sf_initial": det.sf_initial_dist,
                "sf_final": det.sf_final_dist,
                "tp_initial_dbm": det.tp_initial_dist,
                "tp_final_dbm": det.tp_final_dist,
            },
            "adr": {
                "total_changes": det.adr_changes_total,
                "nodes_with_changes": det.nodes_with_adr_changes,
            }
        }
    out_path.write_text(json.dumps(blob, indent=2))

# --------------------- plotting (optional) --------------------------------

def try_plot(summary_df: pd.DataFrame, out_png: Path):
    if summary_df.empty:
        return
    # Only plot rows with valid PDR
    df = summary_df.dropna(subset=["Overall PDR (%)"])
    if df.empty:
        return
    plt.figure(figsize=(14, 7))
    order = sorted(df.index)
    plt.bar(order, df.loc[order, "Overall PDR (%)"])
    plt.xticks(rotation=30, ha="right")
    plt.ylabel("PDR (%)")
    plt.title("Scenario 01 (FLoRa): PDR by Sub-Scenario")
    plt.tight_layout()
    plt.savefig(out_png, dpi=220)


def _out(base: Path, tail: str) -> Path:
    # append a tail to the base path name (without trying to treat it as an extension)
    return base.parent / (base.name + tail)

# --------------------- entry point ---------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Analyze OMNeT++ FLoRa JSON exports for Scenario 01 (deep).")
    ap.add_argument("--json-dir", type=Path, default=Path("json_exports"),
                    help="Folder containing *_extracted.json or the 4 raw JSONs per sub-scenario")
    ap.add_argument("--out-prefix", type=Path, default=Path("scenario_01_flora"),
                    help="Prefix for outputs (summary.csv, per_node.csv, details.json, analysis.png)")
    ap.add_argument("--no-plot", action="store_true", help="Skip generating the overview plot")
    args = ap.parse_args()

    jd = args.json_dir
    if not jd.exists():
        print(f"❌ JSON dir not found: {jd}")
        return

    # Prefer merged, otherwise infer bases from scalars presence
    merged = sorted(jd.glob("scenario-01-baseline-*-s*_extracted.json"))
    if merged:
        bases = {re.sub(r"_extracted\.json$", "", p.name) for p in merged}
    else:
        scal = sorted(jd.glob("scenario-01-baseline-*-s*_scalars.json"))
        bases = {re.sub(r"_scalars\.json$", "", p.name) for p in scal}

    if not bases:
        print("❌ No Scenario-01 JSONs detected.")
        return

    details: List[ScenarioDetails] = []
    per_node_all: List[pd.DataFrame] = []

    for base in sorted(bases):
        res = analyze_subscenario(base, jd)
        if not res:
            continue
        det, per_node_df = res
        details.append(det)
        if isinstance(per_node_df, pd.DataFrame) and not per_node_df.empty:
            per_node_df.insert(1, "Sub-Scenario", det.name)
            per_node_all.append(per_node_df)

    if not details:
        print("❌ Nothing parsed.")
        return

    # Summary table
    rows = [details_to_row(d) for d in details]
    summary_df = pd.DataFrame(rows).set_index("Sub-Scenario").sort_index()
    out_summary = _out(args.out_prefix, "_summary.csv")
    summary_df.to_csv(out_summary)
    print("\nScenario 01 — OMNeT++ FLoRa Summary (rich)")
    print(summary_df.to_string())
    print(f"\n💾 Saved: {out_summary}")

    # Per-node
    if per_node_all:
        pn_df = pd.concat(per_node_all, ignore_index=True)
        out_pn = _out(args.out_prefix, "_per_node.csv")
        pn_df.to_csv(out_pn, index=False)
        print(f"💾 Per-node table: {out_pn}")
    else:
        print("ℹ️  No per-node table available in exports.")

    # Details JSON
    out_json = _out(args.out_prefix, "_details.json")
    save_details_json(details, out_json)
    print(f"💾 Details JSON: {out_json}")

    # Plot (optional)
    if not args.no_plot:
        out_png = _out(args.out_prefix, "_analysis.png")
        try_plot(summary_df, out_png)
        print(f"📈 Plot: {out_png}")


if __name__ == "__main__":
    import re  # used in main for re.sub
    main()
