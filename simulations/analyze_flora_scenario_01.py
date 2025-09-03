# #!/usr/bin/env python3
# # -*- coding: utf-8 -*-
# """
# OMNeT++ FLoRa — Scenario 01 Deep Analyzer
# -----------------------------------------
# Reads either:
#   - merged: scenario-01-baseline-*-s0_extracted.json
#   - raw:    scenario-01-baseline-*-s0_{scalars,parameters,app_vectors,histograms}.json

# Outputs:
#   - scenario_01_flora_summary.csv         (one row per sub-scenario; rich metrics)
#   - scenario_01_flora_per_node.csv        (per-node KPIs when present)
#   - scenario_01_flora_details.json        (structured details per sub-scenario: distributions, energy, radio stats)
#   - scenario_01_flora_analysis.png        (optional compact figure if data available)

# It is intentionally robust:
#   * understands merged (under "extracted_data") and raw layouts
#   * searches multiple possible scalar/vector names
#   * tolerates missing metrics and still produces best-effort results
# """

# from __future__ import annotations
# import argparse
# import json
# import math
# import re
# from collections import Counter, defaultdict
# from dataclasses import dataclass, field
# from pathlib import Path
# from typing import Any, Dict, Iterable, List, Optional, Tuple

# import pandas as pd
# import matplotlib.pyplot as plt

# # --------------------- helpers: time parsing, walking ---------------------

# TIME_UNITS = {"s": 1, "sec": 1, "ms": 1e-3, "us": 1e-6, "min": 60, "h": 3600}

# def parse_time_to_seconds(val: Optional[str]) -> Optional[float]:
#     if val is None:
#         return None
#     s = str(val).strip()
#     if re.fullmatch(r"\d+(\.\d+)?", s):
#         return float(s)
#     m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([A-Za-z]+)\s*", s)
#     if not m:
#         return None
#     num, unit = m.group(1), m.group(2).lower()
#     return float(num) * TIME_UNITS.get(unit, float("nan"))

# def deep_iter(obj: Any) -> Iterable[Dict[str, Any]]:
#     if isinstance(obj, dict):
#         yield obj
#         for v in obj.values():
#             yield from deep_iter(v)
#     elif isinstance(obj, list):
#         for v in obj:
#             yield from deep_iter(v)

# # --------------------- bundle access (merged/raw) -------------------------

# def load_bundle(base_no_suffix: str, json_dir: Path) -> Optional[Dict[str, Any]]:
#     """Return a unified dict representing this sub-scenario."""
#     merged = json_dir / f"{base_no_suffix}_extracted.json"
#     if merged.exists():
#         with open(merged, "r") as f:
#             return json.load(f)

#     need = {
#         "parameters": json_dir / f"{base_no_suffix}_parameters.json",
#         "scalars":    json_dir / f"{base_no_suffix}_scalars.json",
#         "vectors":    json_dir / f"{base_no_suffix}_app_vectors.json",
#         "histograms": json_dir / f"{base_no_suffix}_histograms.json",
#     }
#     for p in need.values():
#         if not p.exists():
#             return None
#     return {k: json.load(open(p, "r")) for k, p in need.items()}

# def get_section(bundle: Dict[str, Any], name: str) -> Dict[str, Any]:
#     """Return 'scalars'|'parameters'|'vectors'|'histograms' section, robust to merged/raw layouts."""
#     if "extracted_data" in bundle and name in bundle["extracted_data"]:
#         return bundle["extracted_data"][name]
#     return bundle.get(name, {})

# # --------------------- lookups: parameters & scalars ----------------------

# def find_param(parameters_section: Dict[str, Any], name_regex: str, module_regex: Optional[str] = None) -> Optional[str]:
#     name_re = re.compile(name_regex)
#     module_re = re.compile(module_regex) if module_regex else None
#     for d in deep_iter(parameters_section):
#         if not isinstance(d, dict):
#             continue
#         if "name" in d and "value" in d:
#             if name_re.search(str(d.get("name", ""))) and (module_re is None or module_re.search(str(d.get("module", "")))):
#                 return d.get("value")
#     return None

# def find_all_params(parameters_section: Dict[str, Any], name_regex: str, module_regex: Optional[str] = None) -> List[Dict[str, Any]]:
#     out = []
#     name_re = re.compile(name_regex)
#     module_re = re.compile(module_regex) if module_regex else None
#     for d in deep_iter(parameters_section):
#         if isinstance(d, dict) and "name" in d and "value" in d:
#             if name_re.search(str(d.get("name", ""))) and (module_re is None or module_re.search(str(d.get("module", "")))):
#                 out.append(d)
#     return out

# def read_server_scalar(scalars_section: Dict[str, Any], names: List[str]) -> Optional[float]:
#     for d in deep_iter(scalars_section):
#         if isinstance(d, dict) and all(k in d for k in ("module", "name", "value")):
#             if str(d["module"]).endswith("networkServer.app[0]") and d["name"] in names:
#                 try:
#                     return float(d["value"])
#                 except Exception:
#                     pass
#     return None

# def sum_node_scalar(scalars_section: Dict[str, Any], name: str, module_tail: str = ".loRaNodes[") -> Optional[float]:
#     total, found = 0.0, False
#     for d in deep_iter(scalars_section):
#         if isinstance(d, dict) and all(k in d for k in ("module", "name", "value")):
#             mod = str(d["module"])
#             if module_tail in mod and d["name"] == name:
#                 try:
#                     total += float(d["value"])
#                     found = True
#                 except Exception:
#                     pass
#     return total if found else None

# def sum_scalar_glob(scalars_section: Dict[str, Any], names: List[str]) -> Dict[str, float]:
#     sums = defaultdict(float)
#     seen = defaultdict(bool)
#     for d in deep_iter(scalars_section):
#         if isinstance(d, dict) and "name" in d and "value" in d:
#             nm = str(d["name"])
#             if nm in names:
#                 try:
#                     sums[nm] += float(d["value"])
#                     seen[nm] = True
#                 except Exception:
#                     pass
#     return {k: (sums[k] if seen[k] else 0.0) for k in names}

# # --------------------- vectors: discovery & reductions --------------------

# def iter_vectors(vectors_section: Dict[str, Any]):
#     """
#     Generator that yields (module, name, values) for every vector found.
#     Supports common merged/raw shapes.
#     values: list of numeric samples (time is ignored for aggregations here)
#     """
#     # merged extractor often stores arrays under fields like "vectors" or nested
#     for d in deep_iter(vectors_section):
#         if not isinstance(d, dict):
#             continue
#         if "module" in d and "name" in d:
#             # seen formats: {"module": "...", "name": "...", "values": [[t,v],...]} or {"x":[], "y":[]}
#             vals = None
#             if "values" in d and isinstance(d["values"], list) and d["values"] and isinstance(d["values"][0], (list, tuple)):
#                 try:
#                     vals = [float(x[1]) for x in d["values"] if len(x) >= 2]
#                 except Exception:
#                     pass
#             elif "y" in d and isinstance(d["y"], list):
#                 try:
#                     vals = [float(y) for y in d["y"]]
#                 except Exception:
#                     pass
#             elif "value" in d and isinstance(d["value"], list):  # rare
#                 try:
#                     vals = [float(y) for y in d["value"]]
#                 except Exception:
#                     pass
#             if vals is not None and len(vals) > 0:
#                 yield str(d["module"]), str(d["name"]), vals

# def last_value(values: List[float]) -> Optional[float]:
#     return values[-1] if values else None

# def avg_value(values: List[float]) -> Optional[float]:
#     return sum(values) / len(values) if values else None

# # --------------------- dataclasses for tidy aggregation -------------------

# @dataclass
# class ScenarioDetails:
#     name: str
#     init_sf: Optional[int] = None
#     init_tp_dbm: Optional[float] = None
#     adr_enabled: Optional[bool] = None
#     n_nodes: Optional[int] = None
#     sim_seconds: Optional[float] = None

#     total_sent: Optional[int] = None
#     total_received: Optional[int] = None
#     pdr_percent: Optional[float] = None

#     # radio pipeline
#     gw_rx_started: Optional[int] = None
#     gw_rx_ok: Optional[int] = None
#     collisions: Optional[int] = None
#     captures: Optional[int] = None

#     # energy (totals over nodes)
#     energy_total_j: Optional[float] = None
#     energy_tx_j: Optional[float] = None
#     energy_rx_j: Optional[float] = None
#     energy_sleep_j: Optional[float] = None

#     # distributions
#     sf_initial_dist: Dict[int, int] = field(default_factory=dict)
#     sf_final_dist: Dict[int, int] = field(default_factory=dict)
#     tp_initial_dist: Dict[int, int] = field(default_factory=dict)
#     tp_final_dist: Dict[int, int] = field(default_factory=dict)

#     # ADR activity
#     adr_changes_total: Optional[int] = None
#     nodes_with_adr_changes: Optional[int] = None

#     # misc
#     channel_util_percent: Optional[float] = None
#     theoretical_toa_ms: Optional[float] = None
#     total_airtime_ms: Optional[float] = None

# # --------------------- extraction & derivation ----------------------------

# def subscenario_name_from_base(base: str) -> str:
#     m = re.search(r"scenario-01-[^-]+-(.+?)-s\d+$", base)
#     return m.group(1) if m else base

# def detect_nodes_count(bundle: Dict[str, Any]) -> Optional[int]:
#     if "node_counts" in bundle and isinstance(bundle["node_counts"], dict):
#         try:
#             return int(bundle["node_counts"].get("end_node", 0)) or None
#         except Exception:
#             pass
#     params = get_section(bundle, "parameters")
#     v = find_param(params, r"numberOfNodes", r"LoRaNetworkTest")
#     try:
#         return int(float(v)) if v is not None else None
#     except Exception:
#         return None

# def detect_sim_seconds(bundle: Dict[str, Any]) -> Optional[float]:
#     params = get_section(bundle, "parameters")
#     lim = find_param(params, r"sim-time-limit", r"^LoRaNetworkTest$")
#     return parse_time_to_seconds(lim) if lim else None

# def detect_adr_flag(bundle: Dict[str, Any], fallback_name: str) -> bool:
#     params = get_section(bundle, "parameters")
#     v = find_param(params, r"evaluateADRinServer", r"networkServer")
#     if v is not None:
#         return str(v).strip().lower() in ("true", "1", "yes", "on")
#     return "adr" in fallback_name.lower()

# def read_totals(bundle: Dict[str, Any]) -> Tuple[Optional[int], Optional[int]]:
#     scal = get_section(bundle, "scalars")
#     sent = sum_node_scalar(scal, "sentPackets")  # best source
#     if sent is None:
#         # compute from parameters as fallback
#         params = get_section(bundle, "parameters")
#         nodes = detect_nodes_count(bundle)
#         tt = find_param(params, r"timeToNextPacket", r"\.app\[0\]$|SimpleLoRaApp")
#         tf = find_param(params, r"timeToFirstPacket", r"\.app\[0\]$|SimpleLoRaApp")  # not used in count
#         nps = find_param(params, r"numberOfPacketsToSend", r"\.app\[0\]$|SimpleLoRaApp")
#         sim_s = detect_sim_seconds(bundle)
#         int_s = parse_time_to_seconds(tt) if tt else None
#         if nodes and sim_s and int_s and int_s > 0:
#             per_node = int(sim_s // int_s)
#             try:
#                 nps_i = int(float(nps)) if nps else 0
#                 if nps_i > 0:
#                     per_node = min(per_node, nps_i)
#             except Exception:
#                 pass
#             sent = nodes * per_node
#     rec = read_server_scalar(scal, ["totalReceivedPackets", "LoRa_ServerPacketReceived:count"])
#     return (int(sent) if sent is not None else None,
#             int(rec) if rec is not None else None)

# def read_pipeline_stats(bundle: Dict[str, Any]) -> Dict[str, int]:
#     scal = get_section(bundle, "scalars")
#     names = [
#         "LoRaGWRadioReceptionStarted:count",
#         "LoRaGWRadioReceptionFinishedCorrect:count",
#         "LoRaReceptionCollision:count",
#         "LoRaReceptionCapture:count",  # if present
#         "LoRa_GWPacketReceived:count",
#     ]
#     sums = sum_scalar_glob(scal, names)
#     # make ints
#     return {k: int(v) for k, v in sums.items()}

# def read_energy_totals(bundle: Dict[str, Any]) -> Dict[str, float]:
#     scal = get_section(bundle, "scalars")
#     # common names in FLoRa energy models
#     candidates = [
#         "energyConsumedJ", "totalEnergyConsumedJ",
#         "txEnergyJ", "rxEnergyJ", "sleepEnergyJ", "idleEnergyJ"
#     ]
#     sums = sum_scalar_glob(scal, candidates)
#     # prefer specific channels if available
#     return {k: float(v) for k, v in sums.items() if v > 0.0}

# def collect_sf_tp_distributions(bundle: Dict[str, Any]) -> Tuple[Counter, Counter, Counter, Counter]:
#     """
#     Builds initial/final distributions for SF and TP.
#     Initial: from parameters if present
#     Final:   from vectors if present (last value per node), else fall back to scalars where available
#     """
#     params = get_section(bundle, "parameters")
#     init_sf = Counter()
#     init_tp = Counter()

#     # initial SF/TP per node if exported per-node
#     per_node_init_sf = find_all_params(params, r"initialLoRaSF", r"\.loRaNodes\[\d+\]\.app\[0\]")
#     for p in per_node_init_sf:
#         try:
#             init_sf[int(float(p["value"]))] += 1
#         except Exception:
#             pass

#     per_node_init_tp = find_all_params(params, r"initialLoRaTP", r"\.loRaNodes\[\d+\]\.app\[0\]")
#     for p in per_node_init_tp:
#         try:
#             # TP often like "14 dBm" -> split number
#             v = str(p["value"]).replace("dBm", "").strip()
#             init_tp[int(round(float(v)))] += 1
#         except Exception:
#             pass

#     # FINAL values from vectors (best effort: search common names)
#     vectors = get_section(bundle, "vectors")
#     sf_last_by_node = {}
#     tp_last_by_node = {}

#     # pattern candidates (module/name)
#     sf_name_res = [re.compile(r"(?:SF|SpreadingFactor|LoRaSF|currentSF)", re.I)]
#     tp_name_res = [re.compile(r"(?:TP|TxPower|currentTP|LoRaTP)", re.I)]

#     for module, name, values in iter_vectors(vectors):
#         if ".loRaNodes[" not in module:
#             continue
#         node_m = re.search(r"\.loRaNodes\[(\d+)\]", module)
#         node_id = int(node_m.group(1)) if node_m else None
#         if node_id is None:
#             continue
#         val_last = last_value(values)
#         if val_last is None:
#             continue

#         # SF?
#         if any(rx.search(name) for rx in sf_name_res):
#             try:
#                 sf_last_by_node[node_id] = int(round(val_last))
#             except Exception:
#                 pass
#         # TP?
#         if any(rx.search(name) for rx in tp_name_res):
#             try:
#                 tp_last_by_node[node_id] = int(round(val_last))
#             except Exception:
#                 pass

#     final_sf = Counter(sf_last_by_node.values())
#     final_tp = Counter(tp_last_by_node.values())
#     return init_sf, final_sf, init_tp, final_tp

# def read_adr_activity(bundle: Dict[str, Any]) -> Tuple[Optional[int], Optional[int]]:
#     scal = get_section(bundle, "scalars")
#     sums = sum_scalar_glob(scal, ["TotalADRChanges", "ADRChanges", "NodesWithADRChanges"])
#     total_changes = int(sums.get("TotalADRChanges", 0) or sums.get("ADRChanges", 0))
#     nodes_changed = int(sums.get("NodesWithADRChanges", 0))
#     return (total_changes if total_changes > 0 else None,
#             nodes_changed if nodes_changed > 0 else None)

# def read_airtime_and_util(bundle: Dict[str, Any]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
#     scal = get_section(bundle, "scalars")
#     # try scenario-wide
#     tot_air_ms = read_server_scalar(scal, ["TotalAirTime_ms"])
#     theo_toa = read_server_scalar(scal, ["TheoreticalToA_ms"])
#     util = read_server_scalar(scal, ["ChannelUtilization_Percent"])
#     # fallbacks: sum across nodes if above not present
#     sums = sum_scalar_glob(scal, ["TotalAirTime_ms", "TheoreticalToA_ms", "ChannelUtilization_Percent"])
#     tot_air_ms = tot_air_ms if tot_air_ms is not None else (sums.get("TotalAirTime_ms") or None)
#     theo_toa = theo_toa if theo_toa is not None else (sums.get("TheoreticalToA_ms") or None)
#     util = util if util is not None else (sums.get("ChannelUtilization_Percent") or None)
#     return theo_toa, tot_air_ms, util

# # --------------------- per-node table (best effort) -----------------------

# def build_per_node_table(bundle: Dict[str, Any]) -> pd.DataFrame:
#     scal = get_section(bundle, "scalars")
#     params = get_section(bundle, "parameters")
#     vectors = get_section(bundle, "vectors")

#     # Sent/energy per node (scalars) — robust
#     per_node = defaultdict(dict)

#     for d in deep_iter(scal):
#         if not isinstance(d, dict): continue
#         if "module" in d and "name" in d and "value" in d:
#             mod, nm, val = str(d["module"]), str(d["name"]), d["value"]
#             node_m = re.search(r"\.loRaNodes\[(\d+)\]", mod)
#             if not node_m: continue
#             nid = int(node_m.group(1))
#             if nm == "sentPackets":
#                 try: per_node[nid]["Sent"] = int(float(val))
#                 except Exception: pass
#             # energy breakdowns
#             if nm in ("energyConsumedJ", "txEnergyJ", "rxEnergyJ", "sleepEnergyJ", "idleEnergyJ"):
#                 try: per_node[nid][nm] = float(val)
#                 except Exception: pass

#     # Initial SF/TP per node (parameters)
#     for p in find_all_params(params, r"initialLoRaSF", r"\.loRaNodes\[(\d+)\]\.app\[0\]"):
#         m = re.search(r"\.loRaNodes\[(\d+)\]", p.get("module",""))
#         if not m: continue
#         nid = int(m.group(1))
#         try: per_node[nid]["InitSF"] = int(float(p["value"]))
#         except Exception: pass

#     for p in find_all_params(params, r"initialLoRaTP", r"\.loRaNodes\[(\d+)\]\.app\[0\]"):
#         m = re.search(r"\.loRaNodes\[(\d+)\]", p.get("module",""))
#         if not m: continue
#         nid = int(m.group(1))
#         try:
#             v = str(p["value"]).replace("dBm","").strip()
#             per_node[nid]["InitTP_dBm"] = float(v)
#         except Exception:
#             pass

#     # Final SF/TP (vectors): last observed
#     sf_name_res = [re.compile(r"(?:SF|SpreadingFactor|LoRaSF|currentSF)", re.I)]
#     tp_name_res = [re.compile(r"(?:TP|TxPower|currentTP|LoRaTP)", re.I)]
#     last_sf_by_node, last_tp_by_node = {}, {}

#     for module, name, values in iter_vectors(vectors):
#         node_m = re.search(r"\.loRaNodes\[(\d+)\]", module)
#         if not node_m: continue
#         nid = int(node_m.group(1))
#         if any(rx.search(name) for rx in sf_name_res):
#             lv = last_value(values)
#             if lv is not None:
#                 try: last_sf_by_node[nid] = int(round(lv))
#                 except Exception: pass
#         if any(rx.search(name) for rx in tp_name_res):
#             lv = last_value(values)
#             if lv is not None:
#                 try: last_tp_by_node[nid] = float(lv)
#                 except Exception: pass

#     for nid, sf in last_sf_by_node.items():
#         per_node[nid]["FinalSF"] = sf
#     for nid, tp in last_tp_by_node.items():
#         per_node[nid]["FinalTP_dBm"] = tp

#     if not per_node:
#         return pd.DataFrame()

#     df = pd.DataFrame.from_dict(per_node, orient="index").reset_index().rename(columns={"index": "NodeID"})
#     cols = ["NodeID","Sent","InitSF","FinalSF","InitTP_dBm","FinalTP_dBm","energyConsumedJ","txEnergyJ","rxEnergyJ","sleepEnergyJ","idleEnergyJ"]
#     for c in cols:
#         if c not in df.columns:
#             df[c] = pd.NA
#     return df[cols]

# # --------------------- top-level analysis per sub-scenario ----------------

# def analyze_subscenario(base: str, json_dir: Path) -> Optional[Tuple[ScenarioDetails, pd.DataFrame]]:
#     bundle = load_bundle(base, json_dir)
#     if not bundle:
#         return None

#     name = subscenario_name_from_base(base)
#     params = get_section(bundle, "parameters")

#     det = ScenarioDetails(name=name)
#     det.adr_enabled = detect_adr_flag(bundle, name)
#     det.n_nodes = detect_nodes_count(bundle)
#     det.sim_seconds = detect_sim_seconds(bundle)

#     # initial SF/TP *global* (if present)
#     i_sf = find_param(params, r"initialLoRaSF", r"\.loRaNodes\[\d+\]\.app\[0\]")
#     i_tp = find_param(params, r"initialLoRaTP", r"\.loRaNodes\[\d+\]\.app\[0\]")
#     try:
#         det.init_sf = int(float(i_sf)) if i_sf is not None else None
#     except Exception:
#         pass
#     try:
#         det.init_tp_dbm = float(str(i_tp).replace("dBm","").strip()) if i_tp is not None else None
#     except Exception:
#         pass

#     # totals
#     det.total_sent, det.total_received = read_totals(bundle)
#     if det.total_sent and det.total_received is not None and det.total_sent > 0:
#         det.pdr_percent = round(100.0 * det.total_received / det.total_sent, 4)

#     # radio pipeline
#     pipe = read_pipeline_stats(bundle)
#     det.gw_rx_started = pipe.get("LoRaGWRadioReceptionStarted:count") or 0
#     det.gw_rx_ok      = pipe.get("LoRaGWRadioReceptionFinishedCorrect:count") or 0
#     det.collisions    = pipe.get("LoRaReceptionCollision:count") or 0
#     det.captures      = pipe.get("LoRaReceptionCapture:count") or 0

#     # energy totals
#     en = read_energy_totals(bundle)
#     det.energy_total_j = en.get("energyConsumedJ") or en.get("totalEnergyConsumedJ")
#     det.energy_tx_j    = en.get("txEnergyJ")
#     det.energy_rx_j    = en.get("rxEnergyJ")
#     det.energy_sleep_j = en.get("sleepEnergyJ") or en.get("idleEnergyJ")

#     # airtime & utilization
#     det.theoretical_toa_ms, det.total_airtime_ms, det.channel_util_percent = read_airtime_and_util(bundle)

#     # SF/TP distributions
#     sf_i, sf_f, tp_i, tp_f = collect_sf_tp_distributions(bundle)
#     det.sf_initial_dist = dict(sorted(sf_i.items()))
#     det.sf_final_dist   = dict(sorted(sf_f.items()))
#     det.tp_initial_dist = dict(sorted(tp_i.items()))
#     det.tp_final_dist   = dict(sorted(tp_f.items()))

#     # ADR activity
#     det.adr_changes_total, det.nodes_with_adr_changes = read_adr_activity(bundle)

#     # per-node table
#     per_node_df = build_per_node_table(bundle)

#     return det, per_node_df

# # --------------------- export helpers ------------------------------------

# def details_to_row(det: ScenarioDetails) -> Dict[str, Any]:
#     row = {
#         "Sub-Scenario": det.name,
#         "Init SF": "Yes" if det.init_sf is not None else "No",
#         "Init TP": "Yes" if det.init_tp_dbm is not None else "No",
#         "ADR Enabled": "Yes" if det.adr_enabled else "No",
#         "Total Sent": det.total_sent or 0,
#         "Total Received": det.total_received or 0,
#         "Overall PDR (%)": det.pdr_percent,
#         "GW RX Started": det.gw_rx_started,
#         "GW RX OK": det.gw_rx_ok,
#         "Collisions": det.collisions,
#         "Captures": det.captures,
#         "Energy Total (J)": det.energy_total_j,
#         "Energy TX (J)": det.energy_tx_j,
#         "Energy RX (J)": det.energy_rx_j,
#         "Energy Sleep/Idle (J)": det.energy_sleep_j,
#         "Channel Utilization (%)": det.channel_util_percent,
#         "Total Airtime (ms)": det.total_airtime_ms,
#         "Theoretical ToA (ms)": det.theoretical_toa_ms,
#         "ADR Changes": det.adr_changes_total,
#         "Nodes With ADR Changes": det.nodes_with_adr_changes,
#     }
#     return row

# def save_details_json(details_list: List[ScenarioDetails], out_path: Path):
#     blob = {}
#     for det in details_list:
#         blob[det.name] = {
#             "init": {
#                 "sf": det.init_sf,
#                 "tp_dbm": det.init_tp_dbm,
#                 "adr_enabled": det.adr_enabled,
#                 "n_nodes": det.n_nodes,
#                 "sim_seconds": det.sim_seconds,
#             },
#             "totals": {
#                 "sent": det.total_sent,
#                 "received": det.total_received,
#                 "pdr_percent": det.pdr_percent,
#             },
#             "radio_pipeline": {
#                 "gw_rx_started": det.gw_rx_started,
#                 "gw_rx_ok": det.gw_rx_ok,
#                 "collisions": det.collisions,
#                 "captures": det.captures,
#             },
#             "airtime": {
#                 "channel_util_percent": det.channel_util_percent,
#                 "total_airtime_ms": det.total_airtime_ms,
#                 "theoretical_toa_ms": det.theoretical_toa_ms,
#             },
#             "energy": {
#                 "total_j": det.energy_total_j,
#                 "tx_j": det.energy_tx_j,
#                 "rx_j": det.energy_rx_j,
#                 "sleep_or_idle_j": det.energy_sleep_j,
#             },
#             "distributions": {
#                 "sf_initial": det.sf_initial_dist,
#                 "sf_final": det.sf_final_dist,
#                 "tp_initial_dbm": det.tp_initial_dist,
#                 "tp_final_dbm": det.tp_final_dist,
#             },
#             "adr": {
#                 "total_changes": det.adr_changes_total,
#                 "nodes_with_changes": det.nodes_with_adr_changes,
#             }
#         }
#     out_path.write_text(json.dumps(blob, indent=2))

# # --------------------- plotting (optional) --------------------------------

# def try_plot(summary_df: pd.DataFrame, out_png: Path):
#     if summary_df.empty:
#         return
#     # Only plot rows with valid PDR
#     df = summary_df.dropna(subset=["Overall PDR (%)"])
#     if df.empty:
#         return
#     plt.figure(figsize=(14, 7))
#     order = sorted(df.index)
#     plt.bar(order, df.loc[order, "Overall PDR (%)"])
#     plt.xticks(rotation=30, ha="right")
#     plt.ylabel("PDR (%)")
#     plt.title("Scenario 01 (FLoRa): PDR by Sub-Scenario")
#     plt.tight_layout()
#     plt.savefig(out_png, dpi=220)


# def _out(base: Path, tail: str) -> Path:
#     # append a tail to the base path name (without trying to treat it as an extension)
#     return base.parent / (base.name + tail)

# # --------------------- entry point ---------------------------------------

# def main():
#     ap = argparse.ArgumentParser(description="Analyze OMNeT++ FLoRa JSON exports for Scenario 01 (deep).")
#     ap.add_argument("--json-dir", type=Path, default=Path("json_exports"),
#                     help="Folder containing *_extracted.json or the 4 raw JSONs per sub-scenario")
#     ap.add_argument("--out-prefix", type=Path, default=Path("scenario_01_flora"),
#                     help="Prefix for outputs (summary.csv, per_node.csv, details.json, analysis.png)")
#     ap.add_argument("--no-plot", action="store_true", help="Skip generating the overview plot")
#     args = ap.parse_args()

#     jd = args.json_dir
#     if not jd.exists():
#         print(f"❌ JSON dir not found: {jd}")
#         return

#     # Prefer merged, otherwise infer bases from scalars presence
#     merged = sorted(jd.glob("scenario-01-baseline-*-s*_extracted.json"))
#     if merged:
#         bases = {re.sub(r"_extracted\.json$", "", p.name) for p in merged}
#     else:
#         scal = sorted(jd.glob("scenario-01-baseline-*-s*_scalars.json"))
#         bases = {re.sub(r"_scalars\.json$", "", p.name) for p in scal}

#     if not bases:
#         print("❌ No Scenario-01 JSONs detected.")
#         return

#     details: List[ScenarioDetails] = []
#     per_node_all: List[pd.DataFrame] = []

#     for base in sorted(bases):
#         res = analyze_subscenario(base, jd)
#         if not res:
#             continue
#         det, per_node_df = res
#         details.append(det)
#         if isinstance(per_node_df, pd.DataFrame) and not per_node_df.empty:
#             per_node_df.insert(1, "Sub-Scenario", det.name)
#             per_node_all.append(per_node_df)

#     if not details:
#         print("❌ Nothing parsed.")
#         return

#     # Summary table
#     rows = [details_to_row(d) for d in details]
#     summary_df = pd.DataFrame(rows).set_index("Sub-Scenario").sort_index()
#     out_summary = _out(args.out_prefix, "_summary.csv")
#     summary_df.to_csv(out_summary)
#     print("\nScenario 01 — OMNeT++ FLoRa Summary (rich)")
#     print(summary_df.to_string())
#     print(f"\n💾 Saved: {out_summary}")

#     # Per-node
#     if per_node_all:
#         pn_df = pd.concat(per_node_all, ignore_index=True)
#         out_pn = _out(args.out_prefix, "_per_node.csv")
#         pn_df.to_csv(out_pn, index=False)
#         print(f"💾 Per-node table: {out_pn}")
#     else:
#         print("ℹ️  No per-node table available in exports.")

#     # Details JSON
#     out_json = _out(args.out_prefix, "_details.json")
#     save_details_json(details, out_json)
#     print(f"💾 Details JSON: {out_json}")

#     # Plot (optional)
#     if not args.no_plot:
#         out_png = _out(args.out_prefix, "_analysis.png")
#         try_plot(summary_df, out_png)
#         print(f"📈 Plot: {out_png}")


# if __name__ == "__main__":
#     import re  # used in main for re.sub
#     main()

#!/usr/bin/env python3
# Scenario-01 Analyzer (Baseline variants) for OMNeT++/FLoRa
# - Matches Scenario-02 script structure and printouts
# - Uses all four JSONs where present (parameters, scalars, histograms/statistics, app_vectors/vectors)
# - Prints per-config Initialization Conditions, a context table, and a multi-config scoreboard
# - Tracks and prints exact keys used; optional --dump-keys to save them
# - Plain ASCII output (no emojis)

from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Iterable
import argparse, json, re, math

# =============================================================================
# Key tracking  (same as Scenario-02)
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
# JSON helpers  (same behavior as Scenario-02)
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
# Parsing helpers  (same as Scenario-02)
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
# File discovery  (generalized from Scenario-02)
# =============================================================================
def find_bundle(json_dir: Path, base_tokens: List[str]) -> Dict[str, Path]:
    pats = [p.lower() for p in base_tokens]
    out: Dict[str, Path] = {}
    for p in json_dir.glob("*.json"):
        name = p.name.lower()
        if all(sub in name for sub in pats):
            if "parameters" in name and "parameters" not in out: out["parameters"] = p
            elif "scalars" in name and "scalars" not in out: out["scalars"] = p
            elif ("histograms" in name or "statistics" in name) and "histograms" not in out: out["histograms"] = p
            elif "app_vectors" in name and "app_vectors" not in out: out["app_vectors"] = p
            elif "vectors" in name and "app_vectors" not in out: out["app_vectors"] = p
    return out

def find_all_bundles_s01(json_dir: Path) -> List[Tuple[str, Dict[str, Path]]]:
    """
    Finds every sub-scenario for scenario-01-baseline-* and returns (label, bundle) pairs.
    """
    # Identify base labels by scanning scalars/parameters names
    bases = set()
    for p in json_dir.glob("*.json"):
        name = p.name
        low = name.lower()
        if "scenario-01" in low and "baseline" in low and re.search(r"-s\d+", low):
            # chop suffix like _scalars.json, _parameters.json, _histograms.json, _app_vectors.json, _extracted.json
            base = re.sub(r"_(parameters|scalars|histograms|statistics|app_vectors|vectors|extracted)\.json$", "", name, flags=re.I)
            bases.add(base)
    out: List[Tuple[str, Dict[str, Path]]] = []
    for base in sorted(bases):
        label = base  # keep original
        toks = [part for part in base.lower().split("-") if part]
        bundle = find_bundle(json_dir, [t for t in toks if t])  # reuse S02 finder
        if bundle.get("parameters") and bundle.get("scalars"):
            out.append((label, bundle))
    return out

# =============================================================================
# Aliases and module selectors (copied from Scenario-02)
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
# Lookups and metric helpers  (same logic as Scenario-02)
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
    # fallback via bins
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

# ---- Sent/received/collisions and GW RX ----
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

# ---- ADR Commands ----
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

# ---- ToA estimation fallbacks ----
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
# Config analysis (same shape as Scenario-02)
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

    return res

# =============================================================================
# Printing (context + scoreboard)
# =============================================================================
def fmt_num(x, digits=2):
    return f"{x:.{digits}f}" if isinstance(x, (int,float)) else "NA"

def print_context_table(rows: List[Dict[str, Any]]) -> None:
    print("\n" + "="*100)
    print("SCENARIO 01 - OMNeT++ FLoRa ANALYSIS RESULTS (context)")
    print("="*100)
    header = ("Configuration","Nodes","SimTime_s","Interval_s","ADR Enabled","Initial SF","Initial TP (dBm)")
    fmt = "{:<40} {:>5} {:>10} {:>11} {:>11} {:>10} {:>17}"
    print(fmt.format(*header))
    for r in rows:
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

def print_scoreboard_multi(rows: List[Dict[str, Any]]) -> None:
    keys = [
        "Total Sent", "Total Received", "Overall PDR (%)",
        "Collisions", "GW Rx Started", "GW Rx OK", "GW RxOK (%)",
        "Total ToA (s)", "Mean SF", "SF7-9 (%)", "SF10-12 (%)",
        "Mean SNIR (dB)", "Median SNIR (dB)",
        "Mean RSSI (dBm)", "Median RSSI (dBm)",
        "ADR Cmds", "ADR Cmds (ED recv)", "ADR Cmds (NS sent)"
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
    print("\n" + "="*120)
    print("SCENARIO 01 - Scoreboard (per configuration)")
    print("="*120)
    for r in rows:
        print(f"\n[{r.get('Configuration','')}]")
        for k in keys:
            print(f"  {labels[k]:<20}: {fmt_num(r.get(k))}")
    print("="*120)

# =============================================================================
# Main
# =============================================================================
def main():
    ap = argparse.ArgumentParser(description="Analyze OMNeT++/FLoRa Scenario 01 (Baseline variants)")
    ap.add_argument("--json-dir", type=Path, default=Path("json_exports"),
                    help="Directory with exported JSON files")
    ap.add_argument("--dump-keys", type=Path, default=None,
                    help="Save used keys to this JSON file")
    args = ap.parse_args()

    if not args.json_dir.exists():
        print(f"JSON directory not found: {args.json_dir}")
        print_used_keys()
        if args.dump_keys: dump_used_keys(args.dump_keys)
        return

    print(f"Searching for scenario files in: {args.json_dir}")
    bundles = find_all_bundles_s01(args.json_dir)
    if not bundles:
        print("No Scenario-01 bundles found (looked for 'scenario-01' + 'baseline' + '-s#').")
        print_used_keys()
        if args.dump_keys: dump_used_keys(args.dump_keys)
        return

    results: List[Dict[str, Any]] = []
    for label, bundle in bundles:
        results.append(analyze_config(bundle, label))

    if not results:
        print("No valid results to analyze.")
        print_used_keys()
        if args.dump_keys: dump_used_keys(args.dump_keys)
        return

    # Context table
    print_context_table(results)

    # Scoreboard
    print_scoreboard_multi(results)

    # Keys used
    print_used_keys()
    if args.dump_keys: dump_used_keys(args.dump_keys)

if __name__ == "__main__":
    main()
