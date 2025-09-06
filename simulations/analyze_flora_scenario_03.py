#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
FLoRa / OMNeT++ – Scenario 03 Analyzer (Spreading Factor Impact, SF7..SF12)

WHAT'S NEW
- --area flag to filter JSON files by area suffix (e.g., 1km or 1x1km).
  Matches filenames that contain _1km or _1x1km (both are accepted for either form).
- Header shows the selected area.
- Vector parsing accepts both "values" and singular "value" arrays.

Scoreboard columns:
  Sent, Received, PDR (%), Utilization (%), Collisions,
  Avg RSSI (dBm), Avg SNIR (dB), Avg SF, Avg TP (dBm)
"""

from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Iterable
import argparse, json, re, math, sys

# ------------------------------- defaults --------------------------------------------
DEFAULT_JSON_DIR = Path("json_exports")
SFS = [7, 8, 9, 10, 11, 12]

# ------------------------------- basic utils -----------------------------------------
def read_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8-sig") as f:
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
    blk = _get_block(obj, "parameters");  return blk.get("parameters", []) if blk else []

def get_scalars_list(obj: Any) -> List[dict]:
    blk = _get_block(obj, "scalars");     return blk.get("scalars", []) if blk else []

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

_NUM = re.compile(r"[-+]?[0-9]+(?:\.[0-9]+)?")
def parse_float(s):
    if s is None: return None
    if isinstance(s, (int, float)): return float(s)
    m = _NUM.search(str(s)); return float(m.group(0)) if m else None

_TIME = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([a-zA-Z]+)?\s*$")
def parse_seconds(s):
    if s is None: return None
    if isinstance(s, (int, float)): return float(s)
    m = _TIME.match(str(s))
    if not m: return None
    v = float(m.group(1)); u = (m.group(2) or "").lower()
    if u in ("", "s", "sec", "secs", "second", "seconds"): return v
    if u in ("ms", "msec", "millisecond", "milliseconds"): return v / 1000.0
    if u in ("min", "m", "minute", "minutes"): return v * 60.0
    if u in ("h", "hr", "hour", "hours"): return v * 3600.0
    return None

def parse_bool(s):
    if isinstance(s, bool): return s
    if s is None: return None
    t = str(s).strip().lower()
    if t in ("true", "yes", "1", "on"): return True
    if t in ("false", "no", "0", "off"): return False
    return None

# ------------------------------- field patterns -------------------------------
PARAM_RX = {
    "nodes":         [re.compile(r"\bnumberOfNodes\b", re.I)],
    "send_interval": [re.compile(r"\btimeToNextPacket\b", re.I), re.compile(r"\bsendInterval\b", re.I)],
    "adr_enabled":   [re.compile(r"\bevaluateADRinServer\b", re.I)],
    "initial_sf":    [re.compile(r"\binitialLoRaSF\b", re.I)],
    "payload_len":   [re.compile(r"\b(appPacketLength|payloadLength|payloadBytes|packetLength|loraPayloadBytes)\b", re.I)],
    "bandwidth":     [re.compile(r"\b(bandwidth|loRaBandwidth|radioBandwidth)\b", re.I)],
    "coding_rate":   [re.compile(r"\b(initialLoRaCR)\b", re.I)],
    "preamble_syms": [re.compile(r"\b(preambleSymbols|preambleLength|preambleLen)\b", re.I)],
    "hdr_enabled":   [re.compile(r"\b(implicitHeader|header)\b", re.I)],
    "crc_enabled":   [re.compile(r"\bcrc\b", re.I)],
    "tx_power":      [re.compile(r"\b(txPower|initialLoRaTP|initialTxPower|txpowerdbm)\b", re.I)],
    "max_tx_duration": [re.compile(r"\b(maxTransmissionDuration|maxTxDuration)\b", re.I)],
    "path_loss_sigma": [re.compile(r"\b(sigma|pathLossSigma|shadowingSigma)\b", re.I)],
}

SCALAR_RX = {
    "total_received":[re.compile(r"\btotalReceivedPackets\b", re.I),
                      re.compile(r"\bLoRa_ServerPacketReceived:count\b", re.I)],
    "sent_primary":  [re.compile(r"^(sentPackets|packetsSent|uplinksSent|totalSentPackets|numSent)$", re.I)],
    "sent_fallback": [re.compile(r"^LoRa_AppPacketSent:count$", re.I)],
    "collisions":    [re.compile(r"\b(numCollisions|collisions)\b", re.I)],
    "gw_rx_started": [re.compile(r"\b(LoRaGWRadioReceptionStarted:count|rx[_\s-]*started)\b", re.I)],
    "gw_rx_ok":      [re.compile(r"\b(LoRaGWRadioReceptionFinishedCorrect:count|rx[_\s-]*ok)\b", re.I)],
    "sim_time":      [re.compile(r"\bsimulated time\b", re.I)],
    "final_sf":      [re.compile(r"\bfinalSF\b", re.I)],
}

NODE_APP = re.compile(r".*\.loRaNodes\[\d+\]\.app\[\d+\]$", re.I)
SERVER   = re.compile(r"LoRaNetworkTest\.networkServer\.app\[0\]", re.I)

def find_param(params, keys):
    for rx in keys:
        for p in params:
            if rx.search(str(p.get("name", ""))):
                return str(p.get("value", ""))
    return None

def pick_scalar(scalars, keys, module_rx: Optional[re.Pattern] = None):
    for rx in keys:
        for s in scalars:
            if module_rx and not module_rx.search(str(s.get("module", ""))): continue
            if rx.search(str(s.get("name", ""))) and s.get("value") is not None:
                try:
                    return float(s["value"])
                except:
                    v = parse_float(s["value"])
                    if v is not None: return v
    return None

# ------------------------------- area helpers ---------------------------------
def area_token_variants(area: Optional[str]) -> List[str]:
    """
    Accepts '1km' or '1x1km' (or spaced variants) and returns tokens to match in filenames.
    We match by presence of '_{token}' anywhere in the filename.
    """
    if not area: return []
    a = str(area).strip().lower().replace(" ", "")
    tokens = {a}
    # map 1x1km -> 1km
    if "x" in a and a.endswith("km"):
        left = a.split("x")[0]
        if left.isdigit():
            tokens.add(f"{left}km")
    # map 1km -> 1x1km
    m = re.match(r"^(\d+)km$", a)
    if m:
        n = m.group(1)
        tokens.add(f"{n}x{n}km")
    return sorted(tokens)

def fname_has_area(fname: str, area_tokens: List[str]) -> bool:
    if not area_tokens: return True
    s = fname.lower()
    return any(f"_{tok}" in s for tok in area_tokens)

# ------------------------------- scanning functions ----------------------------
def name_matches_sf(fname: str, sf: int, area_tokens: List[str]) -> bool:
    s = fname.lower()
    sf_ok = ("scenario-03" in s and "baseline" in s and re.search(rf"\bsf0?{sf}\b", s) is not None)
    return sf_ok and fname_has_area(s, area_tokens)

def find_bundle_s03(json_dir: Path, sf: int, area_tokens: List[str]) -> Dict[str, Path]:
    """
    Scenario-02 style scan in a flat folder, restricted by SF and area tokens.
    - If a single JSON file matches and contains the lists, use it for all roles.
    - Otherwise pick role-specific files by substring in filename.
    """
    bundle: Dict[str, Path] = {}
    candidates: List[Path] = []
    for p in json_dir.glob("*.json"):
        if name_matches_sf(p.name, sf, area_tokens):
            candidates.append(p)
            n = p.name.lower()
            if "parameters" in n and "parameters" not in bundle: bundle["parameters"] = p
            elif "scalars" in n and "scalars" not in bundle: bundle["scalars"] = p
            elif ("histograms" in n or "statistics" in n) and "histograms" not in bundle: bundle["histograms"] = p
            elif "app_vectors" in n and "app_vectors" not in bundle: bundle["app_vectors"] = p
            elif "vectors" in n and "app_vectors" not in bundle and "vectors" not in bundle: bundle["vectors"] = p

    # If still missing roles, try combined JSONs
    roles = ["parameters", "scalars", "histograms", "app_vectors", "vectors"]
    missing = [r for r in roles if r not in bundle]
    if missing and candidates:
        for p in candidates:
            try:
                obj = read_json(p)
            except Exception:
                continue
            if not missing: break
            if "parameters" in missing and get_parameters_list(obj): bundle["parameters"] = p; missing.remove("parameters")
            if "scalars"    in missing and get_scalars_list(obj):    bundle["scalars"]    = p; missing.remove("scalars")
            if "histograms" in missing and get_histograms_list(obj): bundle["histograms"] = p; missing.remove("histograms")
            if ("app_vectors" in missing or "vectors" in missing) and get_vectors_list(obj):
                if "app_vectors" in missing:
                    bundle["app_vectors"] = p; missing.remove("app_vectors")
                elif "vectors" in missing:
                    bundle["vectors"] = p; missing.remove("vectors")

    # Last fallback: if we have at least one JSON matched but still no roles,
    # assign the first JSON to all roles and let downstream extractors cope.
    if not bundle and candidates:
        p = candidates[0]
        bundle = {"parameters": p, "scalars": p, "histograms": p, "app_vectors": p}

    return bundle

def discover_sf_bundles(json_dir: Path, sfs: List[int], area_tokens: List[str]) -> List[Tuple[int, Dict[str, Path]]]:
    out: List[Tuple[int, Dict[str, Path]]] = []
    for sf in sfs:
        b = find_bundle_s03(json_dir, sf, area_tokens)
        if b.get("parameters") and b.get("scalars"):
            out.append((sf, b))
    return out

# ------------------------------- radio/ToA helpers -----------------------------------
def parse_bw_hz(s):
    if s is None: return None
    if isinstance(s, (int, float)): return float(s)
    t = str(s).strip().lower().replace(" ", "")
    m = re.match(r"^([0-9]*\.?[0-9]+)(m?g?k?)hz?$", t)
    if m:
        val = float(m.group(1)); suf = m.group(2)
        return val*1e9 if suf in ("g", "ghz") else val*1e6 if suf in ("m", "mhz") else val*1e3 if suf in ("k", "khz") else val
    try: return float(t)
    except: return None

def lora_toa_seconds(payload_bytes: int, sf: int, bw_hz: float, cr: int,
                     preamble_syms: int = 8, header_enabled: bool = True, crc_enabled: bool = True) -> float:
    Tsym = (2.0 ** int(sf)) / float(bw_hz)
    IH = 0 if header_enabled else 1
    CRC = 1 if crc_enabled else 0
    DE = 1 if (int(sf) >= 11 and float(bw_hz) <= 125000.0) else 0
    num = (8*int(payload_bytes) - 4*int(sf) + 28 + 16*CRC - 20*IH)
    den = (4 * (int(sf) - 2*DE))
    payloadSymbNb = 8 + math.ceil(max(0.0, num/den)) * (int(cr) + 4)
    return (int(preamble_syms) + 4.25) * Tsym + payloadSymbNb * Tsym

def estimate_sf(params, scalars) -> int:
    v = pick_scalar(scalars, [SCALAR_RX["final_sf"][0]])
    if isinstance(v, (int, float)) and 7 <= int(v) <= 12: return int(v)
    v = find_param(params, PARAM_RX["initial_sf"])
    n = parse_float(v) if v is not None else None
    return int(n) if n is not None and 7 <= int(n) <= 12 else 12

def estimate_radio_params(params) -> Tuple[float, int, int, bool, bool]:
    bw = parse_bw_hz(find_param(params, PARAM_RX["bandwidth"])) or 125000.0
    cr = int(parse_float(find_param(params, PARAM_RX["coding_rate"])) or 1);  cr = 1 if cr < 1 or cr > 4 else cr
    pre = int(parse_float(find_param(params, PARAM_RX["preamble_syms"])) or 8)
    hdr = parse_bool(find_param(params, PARAM_RX["hdr_enabled"])); header_enabled = True if hdr is None else bool(hdr)
    crc = parse_bool(find_param(params, PARAM_RX["crc_enabled"])); crc_enabled   = True if crc is None else bool(crc)
    return float(bw), int(cr), int(pre), header_enabled, crc_enabled

def payload_bytes_estimate(params, histograms, scalars=None) -> Optional[int]:
    # 1) Histograms/statistics
    total_sum = 0.0; total_cnt = 0.0
    for h in histograms:
        nm = (h.get("name", "") or "").lower()
        if re.search(r"(incomingpacketlengths|packetlength|payloadlength)", nm):
            stat = h.get("stat", {})
            if isinstance(stat, dict) and stat.get("count") and stat.get("sum") is not None:
                try:
                    total_sum += float(stat["sum"]); total_cnt += float(stat["count"])
                except: pass
    if total_cnt > 0:
        return int(round(total_sum / total_cnt))

    # 2) Scalars per-node
    if isinstance(scalars, list):
        per_node_sent = {}
        per_node_bytes = {}
        node_re = re.compile(r"loRaNodes\[(\d+)\]", re.I)
        for s in scalars:
            mod = s.get("module", "") or ""
            nm  = s.get("name", "") or ""
            val = s.get("value", None)
            if val is None:
                continue
            m = node_re.search(mod)
            if not m:
                continue
            node = int(m.group(1))
            if nm in ("sentPackets", "LoRa_AppPacketSent:count"):
                try: per_node_sent[node] = int(float(val))
                except: pass
            elif nm == "incomingPacketLengths:sum" and ".LoRaNic.queue" in mod:
                try: per_node_bytes[node] = int(float(val))
                except: pass
        per_node_pl = []
        for n, sent in per_node_sent.items():
            bytes_sum = per_node_bytes.get(n, None)
            if sent and bytes_sum is not None:
                per_node_pl.append(bytes_sum / sent)
        if per_node_pl:
            return int(round(sum(per_node_pl) / len(per_node_pl)))

    # 3) Parameters fallback
    v = find_param(params, PARAM_RX["payload_len"]); n = parse_float(v) if v is not None else None
    return int(round(n)) if n is not None else None

# ------------------------------- metric extraction -----------------------------------
def extract_init(params, scalars) -> Dict[str, Any]:
    d = {}
    v = find_param(params, PARAM_RX["nodes"]);              d["numberOfNodes"] = int(parse_float(v) or 0) if v is not None else None
    v = find_param(params, PARAM_RX["send_interval"]);      d["sendInterval_s"] = parse_seconds(v) if v is not None else None
    v = pick_scalar(scalars, SCALAR_RX["sim_time"]);        d["simTime_s"] = float(v) if v is not None else None; d["simTime_min"] = d["simTime_s"]/60.0 if d["simTime_s"] else None
    v = find_param(params, PARAM_RX["adr_enabled"]);        b = parse_bool(v) if v is not None else None; d["evaluateADRinServer"] = bool(b) if b is not None else None
    v = find_param(params, PARAM_RX["initial_sf"]);         d["initialSF"] = int(parse_float(v) or 12) if v is not None else None
    tp= find_param(params, PARAM_RX["tx_power"]);           d["initialTP_dBm"] = parse_float(tp) if tp is not None else None
    bw= parse_bw_hz(find_param(params, PARAM_RX["bandwidth"])); d["bandwidth_Hz"] = bw if bw is not None else None
    cr= find_param(params, PARAM_RX["coding_rate"]);        d["codingRate"] = parse_float(cr) if cr is not None else None
    pre=find_param(params, PARAM_RX["preamble_syms"]);      d["preambleSymbols"] = int(parse_float(pre) or 8) if pre is not None else None
    hdr=find_param(params, PARAM_RX["hdr_enabled"]);        d["headerEnabled"] = True if parse_bool(hdr) is None else bool(parse_bool(hdr))
    crc=find_param(params, PARAM_RX["crc_enabled"]);        d["crcEnabled"]   = True if parse_bool(crc) is None else bool(parse_bool(crc))
    mtd=find_param(params, PARAM_RX["max_tx_duration"]);    d["maxTxDuration_s"] = parse_seconds(mtd) if mtd is not None else None
    sigma=find_param(params, PARAM_RX["path_loss_sigma"]);  d["pathLossSigma_dB"] = parse_float(sigma) if sigma is not None else None

    if all(isinstance(x,(int,float)) for x in (d.get("simTime_s"), d.get("sendInterval_s"))) and d["sendInterval_s"] > 0:
        d["expectedPktsPerDevice"] = int(d["simTime_s"] / d["sendInterval_s"])

    return d

def sum_sent_packets_unique(scalars: List[dict]) -> int:
    per_node = {}
    for s in scalars:
        mod = s.get("module", "") or ""; nm = s.get("name", "") or ""; v = s.get("value", None)
        if v is None or not NODE_APP.fullmatch(mod): continue
        slot = "primary" if any(rx.fullmatch(nm) for rx in SCALAR_RX["sent_primary"]) \
               else ("secondary" if SCALAR_RX["sent_fallback"][0].fullmatch(nm) else None)
        if not slot: continue
        node_m = re.search(r"loRaNodes\[(\d+)\]", mod, re.I)
        if not node_m: continue
        node = int(node_m.group(1))
        per_node.setdefault(node, {})
        if slot == "primary" and "primary" not in per_node[node]:
            per_node[node]["primary"] = float(v)
        elif slot == "secondary" and "primary" not in per_node[node] and "secondary" not in per_node[node]:
            per_node[node]["secondary"] = float(v)
    total = 0.0
    for d in per_node.values():
        total += d["primary"] if "primary" in d else d.get("secondary", 0.0)
    return int(total)

def pick_total_received(scalars: List[dict]) -> Optional[int]:
    v = pick_scalar(scalars, SCALAR_RX["total_received"], module_rx=SERVER)
    if v is None:
        v = pick_scalar(scalars, SCALAR_RX["total_received"], module_rx=None)
    return int(v) if v is not None else None

def sum_collisions(scalars: List[dict]) -> Optional[int]:
    total = 0
    found = False
    for s in scalars:
        nm = s.get("name", "") or ""
        if any(rx.search(nm) for rx in SCALAR_RX["collisions"]):
            val = s.get("value", None)
            if val is not None:
                try:
                    total += int(float(val)); found = True
                except: pass
    return total if found else None

def pick_total_airtime_seconds(scalars: List[dict], histograms: List[dict]) -> Optional[float]:
    total = 0.0; used = False
    for h in histograms:
        nm = (h.get("name", "") or "").lower()
        if any(k in nm for k in ("airtime", "time on air", "toa", "tx duration", "tx time")):
            stat = h.get("stat", {})
            if isinstance(stat, dict) and "sum" in stat:
                try: total += float(stat["sum"]); used = True
                except: pass
    if used: return total
    for s in scalars:
        nm = (s.get("name", "") or "").lower()
        if any(k in nm for k in ("airtime", "time on air", "toa", "tx duration", "tx time")):
            try: total += float(s.get("value", 0)); used = True
            except:
                v = parse_float(s.get("value"))
                if v is not None: total += v; used = True
    return total if used else None

def _values_from_vector_entry(vec: dict) -> List[float]:
    # Handles either "values": [...] or "value": [...]
    raw = None
    if isinstance(vec.get("values"), list):
        raw = vec["values"]
    elif isinstance(vec.get("value"), list):
        raw = vec["value"]
    if not raw: return []
    out = []
    for x in raw:
        try: out.append(float(x))
        except: pass
    return out

def extract_avg_sf_tp_from_vectors(vectors) -> Tuple[Optional[float], Optional[float]]:
    """Extract average SF and TP from vectors if available."""
    avg_sf = None
    avg_tp = None
    for v in vectors:
        name = v.get("name", "")
        if name == "SF Vector":
            vals = _values_from_vector_entry(v)
            if vals:
                try: avg_sf = sum(vals) / len(vals)
                except: pass
        elif name == "TP Vector":
            vals = _values_from_vector_entry(v)
            if vals:
                try: avg_tp = sum(vals) / len(vals)
                except: pass
    return avg_sf, avg_tp

# ------------------------------- analyze one SF --------------------------------------
def analyze_one(bundle: Dict[str, Path], label: str) -> Dict[str, Any]:
    params_obj     = read_json(bundle["parameters"])
    scalars_obj    = read_json(bundle["scalars"])
    histograms_obj = read_json(bundle["histograms"]) if "histograms" in bundle else {}
    vectors_obj    = read_json(bundle.get("app_vectors", bundle.get("vectors"))) if ("app_vectors" in bundle or "vectors" in bundle) else {}

    params     = get_parameters_list(params_obj)
    scalars    = get_scalars_list(scalars_obj)
    histograms = get_histograms_list(histograms_obj)
    vectors    = get_vectors_list(vectors_obj)

    init = extract_init(params, scalars)
    sim_s, interval_s, nodes = init.get("simTime_s"), init.get("sendInterval_s"), init.get("numberOfNodes")

    sent = sum_sent_packets_unique(scalars)
    recv = pick_total_received(scalars)
    expected = int((sim_s/interval_s)*nodes) if all(isinstance(x,(int,float)) for x in (sim_s, interval_s, nodes)) and interval_s>0 else None
    pdr = 100.0*recv/sent if (recv is not None and sent>0) else None

    toa_s = pick_total_airtime_seconds(scalars, histograms)
    theor_ms = None
    if toa_s is None:
        pl = payload_bytes_estimate(params, histograms, scalars)
        if pl is not None:
            sf = estimate_sf(params, scalars)
            bw, cr, pre, hdr, crc = estimate_radio_params(params)
            per_pkt = lora_toa_seconds(pl, sf, bw, cr, pre, hdr, crc)
            theor_ms = per_pkt * 1000.0
            toa_s = per_pkt * sent

    util = 100.0*toa_s/sim_s if (isinstance(toa_s,(int,float)) and isinstance(sim_s,(int,float)) and sim_s>0) else None

    # Calculate theoretical per-packet time if still missing
    if theor_ms is None:
        pl = payload_bytes_estimate(params, histograms, scalars)
        if pl is not None:
            sf = estimate_sf(params, scalars)
            bw, cr, pre, hdr, crc = estimate_radio_params(params)
            theor_ms = 1000.0 * lora_toa_seconds(pl, sf, bw, cr, pre, hdr, crc)

    collisions = sum_collisions(scalars)

    # RF averages
    rssi_mean = None
    for h in histograms:
        if h.get("name") == "receivedRSSI":
            try: rssi_mean = float(h.get("mean"))
            except: pass
            break

    snir_mean = None
    tot_cnt = 0.0; tot_sum = 0.0
    for h in histograms:
        if h.get("name") == "minSnir:histogram":
            cnt = h.get("count", 0); mean = h.get("mean", None)
            if mean is not None and cnt:
                try:
                    tot_cnt += float(cnt); tot_sum += float(cnt) * float(mean)
                except: pass
    if tot_cnt > 0: snir_mean = tot_sum / tot_cnt

    # Avg SF/TP from vectors with fallback
    avg_sf, avg_tp = extract_avg_sf_tp_from_vectors(vectors)
    if avg_sf is None:
        avg_sf = estimate_sf(params, scalars)
    if avg_tp is None:
        avg_tp = init.get("initialTP_dBm")
        if avg_tp is None:
            tp_param = find_param(params, PARAM_RX["tx_power"])
            avg_tp = parse_float(tp_param) if tp_param is not None else None

    return {
        "Configuration": label,
        "Sent": sent,
        "Received": recv,
        "PDR (%)": pdr,
        "Utilization (%)": util,
        "Collisions": int(collisions) if isinstance(collisions,(int,float)) else None,
        "Avg RSSI (dBm)": rssi_mean,
        "Avg SNIR (dB)": snir_mean,
        "Avg SF": avg_sf,
        "Avg TP (dBm)": avg_tp,
        "_init": init,
    }

# ------------------------------- printing --------------------------------------------
def fmt_cell(v, dec):
    if v is None: return "NA"
    if isinstance(v, int) and (dec is None or dec == 0):
        return str(v)
    if isinstance(v, float):
        if dec is None:
            if abs(v - round(v)) < 1e-9:
                return str(int(round(v)))
            return f"{v:.2f}"
        return f"{v:.{dec}f}"
    return str(v)

def print_init_conditions_per_scenario(rows):
    if not rows: return
    rows_sorted = sorted(rows, key=lambda r: r.get("Avg SF", 99))
    for r in rows_sorted:
        init = r.get("_init", {})
        sf = r.get("Avg SF", "unknown")
        print(f"\n=== INITIALIZATION CONDITIONS: scenario-03-baseline-sf{sf} ===")
        print("-" * 65)
        def line(lbl, key, unit=""):
            val = init.get(key, "NOT FOUND")
            u = f" {unit}" if unit and val != 'NOT FOUND' else ""
            print(f"{lbl:<25}: {val}{u}")

        line("Number of Nodes", "numberOfNodes")
        line("Simulation Time", "simTime_min", "min")
        line("Send Interval", "sendInterval_s", "s")
        line("ADR Enabled", "evaluateADRinServer")
        print("-" * 30)
        line("Initial SF", "initialSF")
        line("Initial TP", "initialTP_dBm", "dBm")
        line("Bandwidth", "bandwidth_Hz", "Hz")
        line("Coding Rate", "codingRate")
        line("Max TX Duration", "maxTxDuration_s", "s")
        line("Path Loss Sigma", "pathLossSigma_dB", "dB")
        line("Expected pkts/device", "expectedPktsPerDevice")
        print("=" * 65)

def print_scoreboard(rows, area_str: Optional[str]):
    columns = [
        ("Config",        "Configuration",    None, 12),
        ("Sent",          "Sent",             None, 6),
        ("Received",      "Received",         None, 8),
        ("PDR(%)",        "PDR (%)",          2,    7),
        ("Util(%)",       "Utilization (%)",  2,    7),
        ("Collisions",    "Collisions",       None, 10),
        ("Avg RSSI(dBm)", "Avg RSSI (dBm)",   2,    13),
        ("Avg SNIR(dB)",  "Avg SNIR (dB)",    2,    11),
        ("avg SF",        "Avg SF",           1,    6),
        ("avg TP(dBm)",   "Avg TP (dBm)",     1,    11),
    ]

    rows_sorted = sorted(rows, key=lambda r: r.get("Avg SF", 99))

    print("\n" + "="*110)
    title = "SCENARIO 03 — Spreading Factor Impact (FLoRa) — SCOREBOARD"
    if area_str:
        title += f"  (area: {area_str})"
    print(title)
    print("="*110)

    header_parts = []
    for hdr, _, _, width in columns:
        header_parts.append(hdr.ljust(width) if hdr == "Config" else hdr.rjust(width))
    print(" ".join(header_parts))
    print("-" * 110)

    for r in rows_sorted:
        row_parts = []
        for hdr, key, dec, width in columns:
            val = fmt_cell(r.get(key), dec)
            row_parts.append(val.ljust(width) if hdr == "Config" else val.rjust(width))
        print(" ".join(row_parts))
    print("="*110)

def print_apples_to_apples(rows):
    keys = [
        ("numberOfNodes", "Nodes"),
        ("simTime_s", "Sim Time (s)"),
        ("sendInterval_s", "Send Interval (s)"),
        ("bandwidth_Hz", "Bandwidth (Hz)"),
        ("codingRate", "Coding Rate"),
        ("Payload (B)", "Payload (B)"),
        ("preambleSymbols", "Preamble"),
        ("headerEnabled", "Header (explicit)"),
        ("crcEnabled", "CRC Enabled"),
        ("initialTP_dBm", "TX Power (dBm)"),
    ]
    print("\n--- Apples-to-apples checks ---")
    for k, label in keys:
        vals = []
        for r in rows:
            if k in r.get("_init", {}):
                vals.append(r["_init"].get(k))
            else:
                vals.append(r.get(k))
        uniq = sorted(set([str(v) for v in vals if v is not None]))
        status = "OK" if len(uniq) <= 1 else "DRIFT"
        print(f"{label:<22}: {uniq[0] if uniq else 'NA'}   [{status}]")
        if status == "DRIFT":
            print("  values:", ", ".join(uniq))

def print_field_documentation():
    print("\n" + "="*80)
    print("FIELD NAMES USED FROM JSON FILES")
    print("="*80)
    print("\n--- PARAMETERS EXTRACTED ---")
    for key, patterns in PARAM_RX.items():
        print(f"{key}:")
        for pattern in patterns:
            print(f"  - {pattern.pattern}")
    print("\n--- SCALARS EXTRACTED ---")
    for key, patterns in SCALAR_RX.items():
        print(f"{key}:")
        for pattern in patterns:
            print(f"  - {pattern.pattern}")
    print("\n--- HISTOGRAMS EXTRACTED ---")
    print("incomingPacketLengths:histogram  - for payload size estimation")
    print("receivedRSSI                     - for average RSSI calculation")
    print("minSnir:histogram                - for average SNIR calculation")
    print("\n--- VECTORS EXTRACTED ---")
    print("SF Vector                        - spreading factor changes over time")
    print("TP Vector                        - transmission power changes over time")
    print("Vector of RSSI per node          - RSSI measurements per node")
    print("Vector of SNIR per node          - SNIR measurements per node")
    print("\n--- MODULE PATTERNS MATCHED ---")
    print("Node applications:               .*\\.loRaNodes\\[\\d+\\]\\.app\\[\\d+\\]$")
    print("Network server:                  LoRaNetworkTest\\.networkServer\\.app\\[0\\]")
    print("Node NIC queues:                 .*\\.LoRaNic\\.queue")

# ------------------------------- main -------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Analyze FLoRa Scenario 03 (SF Impact) — now area-aware.")
    ap.add_argument("--json-dir", type=Path, default=DEFAULT_JSON_DIR,
                    help="Folder with scenario-03 JSONs (combined or split files)")
    ap.add_argument("--sfs", type=int, nargs="*", default=SFS, help="SFs to include (default: 7..12)")
    ap.add_argument("--area", type=str, default=None,
                    help="Area suffix to filter files (e.g., '1km' or '1x1km'). Matches filenames containing _<area>.")
    ap.add_argument("--show-fields", action="store_true", help="Show all field names used from JSON files")
    args = ap.parse_args()

    if not args.json_dir.exists():
        print(f"[ERR] JSON directory not found: {args.json_dir}"); sys.exit(2)

    area_tokens = area_token_variants(args.area)
    bundles = discover_sf_bundles(args.json_dir, args.sfs, area_tokens)
    if not bundles:
        area_msg = f" (area={args.area})" if args.area else ""
        print(f"[ERR] No SF bundles found in {args.json_dir}{area_msg}. "
              f"Expected names like 'scenario-03-baseline-sf7_1km_scalars.json'.")
        sys.exit(3)

    results = []
    for sf, b in bundles:
        try:
            results.append(analyze_one(b, f"sf{sf}-fixed"))
        except Exception as e:
            print(f"[WARN] SF{sf} failed: {e}", file=sys.stderr)

    if not results:
        print("[ERR] No results parsed."); sys.exit(4)

    print_init_conditions_per_scenario(results)
    print_scoreboard(results, args.area)
    print_apples_to_apples(results)

    if args.show_fields:
        print_field_documentation()

if __name__ == "__main__":
    main()
