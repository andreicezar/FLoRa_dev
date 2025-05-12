
import math
import os
import json
import glob
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import re
import shutil
from collections import defaultdict
from matplotlib.colors import to_hex

class LoRaMetricExtractor:
    def __init__(self, input_path, output_path, prefix=None):
        self.input_path = input_path
        self.output_path = output_path
        self.prefix = prefix
        os.makedirs(self.output_path, exist_ok=True)
        self.vectors = []
        self.scalars = []
        self.tp_vectors = []
        self.sf_vectors = []
        self.snir_vectors = []
        self.rssi_vectors = []
        self.scalar_dict = defaultdict(list)
        self.report_lines = [] 
        self.final_sf = {}
        self.final_tp = {}
        self.data_error_rate_per_node  = []
        self.packet_delivery_ratio_per_node  = []
        self.packet_error_rate_per_node = []
        self.server_der_scalars  = []
        self.data_extraction_rate_per_gateway = {}  # LoRaGW[x] -> DER
        self.data_extraction_rate_per_sf = {}       # SFx -> DER
        self.packets_received_per_gateway = {}

    def load_data(self):
        print(f"📂 Processing input path: {self.input_path}, prefix: {self.prefix}")
        app_file = self._find_file('_app')
        scalars_file = self._find_file('_scalars')

        with open(app_file) as f:
            app_data = json.load(f)
        with open(scalars_file) as f:
            scalar_data = eval("\n".join(line for line in f if not line.strip().startswith("#")))

        run_id_app = next(iter(app_data))
        run_id_scalars = next(iter(scalar_data))

        if run_id_app != run_id_scalars:
            self.report_lines.append(f"⚠️ Run ID mismatch: app='{run_id_app}' vs scalars='{run_id_scalars}'. Trying to use scalar run id.")

        self.vectors = app_data.get(run_id_app, {}).get("vectors", [])
        self.scalars = scalar_data.get(run_id_scalars, {}).get("scalars", [])

        self._sort_into_vectors()
        self._log_vector_values()
        self._sort_into_scalars()
        self._extract_metrics()
        self._log_scalar_summary()
        self.save_report()

    def _extract_metrics(self): 
        for scalar in self.scalars:
            name = scalar.get("name", "")
            module = scalar.get("module", "")
            value = scalar.get("value", None)
            if value is None:
                continue

            node_id = None
            if "[" in module and "loRaNodes" in module:
                m = re.search(r"\[(\d+)\]", module)
                if m:
                    node_id = int(m.group(1))
            elif "numReceivedFromNode" in name:
                m = re.search(r"numReceivedFromNode\s*(\d+)", name)
                if m:
                    node_id = int(m.group(1))

            # Final SF / TP per node
            if "finalSF" in name and node_id is not None:
                self.final_sf[node_id] = int(value)

            elif "finalTP" in name and node_id is not None:
                self.final_tp[node_id] = int(value)

            elif "sentPackets" in name and node_id is not None:
                self.scalar_dict[node_id].append(["sent", int(value)])

            elif "numReceivedFromNode" in name and node_id is not None:
                self.scalar_dict[node_id].append(["received", int(value)])

            # Server DER scalar
            elif "LoRa_NS_DER" in name:
                self.server_der_scalars.append({
                    "entity_type": "server",
                    "name": name,
                    "value": value
                })

            # DER per Gateway
            elif "Data Extraction Rate" in name and "LoRaGWNic" in module:
                gw_match = re.search(r"loraGW\[(\d+)\]", module, re.IGNORECASE)
                if gw_match:
                    gw_id = int(gw_match.group(1))
                    self.data_extraction_rate_per_gateway[gw_id] = float(value)

            # DER per SF
            elif name.startswith("DER SF") and "networkServer" in module:
                sf_match = re.search(r"SF(\d+)", name)
                if sf_match:
                    sf = int(sf_match.group(1))
                    self.data_extraction_rate_per_sf[sf] = float(value)

            # Received packets per Gateway
            elif "LoRa_GWPacketReceived:count" in name and "packetForwarder" in module:
                gw_match = re.search(r"loRaGW\[(\d+)\]", module, re.IGNORECASE)
                if gw_match:
                    gw_id = int(gw_match.group(1))
                    self.packets_received_per_gateway[gw_id] = int(value)

        # Compute DER / PDR / PER per node
        for node_id in sorted(k for k in self.scalar_dict if isinstance(k, int)):
            vals = self.scalar_dict[node_id]
            sent = received = None
            for item in vals:
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    k, v = item
                    if k == "sent":
                        sent = v
                    elif k == "received":
                        received = v
            if sent is not None and received is not None:
                per = (sent - received) / sent if sent > 0 else 0
                pdr = received / sent if sent > 0 else 0
                der = pdr
                self.packet_error_rate_per_node.append({"node_id": node_id, "per": round(per, 4), "sent": sent, "received": received})
                self.packet_delivery_ratio_per_node.append({"node_id": node_id, "pdr": round(pdr, 4), "sent": sent, "received": received})
                self.data_error_rate_per_node.append({"node_id": node_id, "data_error_rate": round(1 - der, 4), "sent": sent, "received": received})

    def save_report(self):
        report_path = os.path.join(self.output_path, "report.txt")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(self.report_lines))
        print(f"📄 Report saved to: {report_path}")

    def _find_file(self, suffix):
        candidates = glob.glob(os.path.join(self.input_path, f"*{suffix}.json"))
        if self.prefix:
            candidates = [f for f in candidates if os.path.basename(f).startswith(self.prefix)]
        if not candidates:
            raise FileNotFoundError(f"No file with suffix '{suffix}.json' and prefix '{self.prefix}' found in {self.input_path}")
        return candidates[0]

    def _sort_into_vectors(self):
        for vec in self.vectors:
            name = vec.get("name", "")
            if 'tp vector' in name.lower():
                self.tp_vectors.append(vec)
            elif 'sf vector' in name.lower():
                self.sf_vectors.append(vec)
            elif 'snir' in name.lower():
                if 'networkserverapp' in vec['module'].lower():
                    self.snir_vectors = [vec]  # vector global
                else:
                    self.snir_vectors.append(vec)  # vectori per nod
            elif 'rssi' in name.lower():
                self.rssi_vectors.append(vec)

        self._plot_all_vectors_as_histograms()

    def _plot_all_vectors_as_histograms(self):
        vector_sets = [
            (self.sf_vectors, 'SF Vector', self._get_node_id_from_module),
            (self.tp_vectors, 'TP Vector', self._get_node_id_from_module),
            (self.snir_vectors, 'SNIR', self._get_index_id),
            (self.rssi_vectors, 'RSSI', self._get_index_id)
        ]

        for vectors, label, id_func in vector_sets:
            if not vectors:
                continue

            ids = [id_func(i, vec["module"]) for i, vec in enumerate(vectors)]
            unique_ids = sorted(set(ids))

            cmap = plt.get_cmap('hsv')
            color_map = {nid: cmap(i / len(unique_ids)) for i, nid in enumerate(unique_ids)}

            plt.figure(figsize=(12, 7))

            if label == 'SNIR' and len(vectors) == 1 and 'networkserverapp' in vectors[0]['module'].lower():
                snir_per_node = self.split_vector_by_node(vectors[0], num_nodes=10)
                plt.figure()
                for node_id, values in snir_per_node.items():
                    plt.hist(values, bins=30, alpha=0.6, label=f"Node {node_id}")
                plt.title("SNIR Histogram per Node (from combined vector)")
                plt.xlabel("SNIR (dB)")
                plt.ylabel("Frequency")
                plt.legend()
                plt.grid(True)
                plt.savefig(os.path.join(self.output_path, "SNIR_histogram_split_by_node.png"))
                plt.close()
                return

            histogram_data = []
            label_added = False
            for i, vec in enumerate(vectors):
                values = vec.get("value", [])
                nid = id_func(i, vec["module"])
                if isinstance(values, list) and values:
                    counts, bins, _ = plt.hist(values, bins=20, alpha=0.6, label=str(nid), color=color_map.get(nid, None))
                    histogram_data.extend((x, y) for x, y in zip(bins, counts))
                    label_added = True

            histogram_data = sorted(histogram_data, key=lambda t: t[1])
            seen = set()
            for x, y in histogram_data:
                key = (round(x, 2), int(y))
                if key in seen or y == 0:
                    continue
                seen.add(key)
                plt.text(x, y, f"{int(y)}", fontsize=7, rotation=0, ha='center', va='bottom')

            plt.title(f"{label} Histogram per Node")
            plt.xlabel("Frequency")
            plt.ylabel(label)
            if label_added:
                plt.legend(fontsize='small', loc='best')
            else:
                self.report_lines.append(f"⚠️ No labels added for legend in {label} plot.")
            plt.grid(True)
            fname = f"{label.replace(' ', '_')}_histogram_all_nodes.png"
            plt.savefig(os.path.join(self.output_path, fname))
            plt.close()
            print(f"✅ Saved plot: {fname}")

    def calculate_toa_per_node(self, payload_size=15, bw=125000, cr=1, preamble=8, header_enabled=True):
        def calculate_lora_toa(payload_size, sf, bw, cr, preamble, header_enabled, de=None):
            tsym = (2 ** sf) / bw
            if de is None:
                de = 1 if tsym > 0.016 else 0
            h = 0 if header_enabled else 1
            payload_symb_nb = 8 + max(
                math.ceil(
                    (8 * payload_size - 4 * sf + 28 + 16 - 20 * h)
                    / (4 * (sf - 2 * de))
                ) * (cr + 4),
                0
            )
            t_payload = payload_symb_nb * tsym
            t_preamble = (preamble + 4.25) * tsym
            return (t_preamble + t_payload) * 1000  # ms

        toa_per_node = {}
        for node_id in sorted(self.final_sf.keys()):
            if node_id not in self.scalar_dict:
                print(f"⚠️ Node {node_id} not found in scalar_dict.")
                continue

            sent = None
            for k, v in self.scalar_dict[node_id]:
                if k == "sent":
                    sent = v
                    break

            if sent is None:
                print(f"⚠️ No 'sent' entry found for node {node_id}")
                continue

            sf = self.final_sf.get(node_id, None)
            if sf is None:
                print(f"⚠️ No finalSF found for node {node_id}")
                continue

            toa_single = calculate_lora_toa(payload_size, sf, bw, cr, preamble, header_enabled)
            toa_total = toa_single * sent
            toa_per_node[node_id] = {
                "sf": sf,
                "sent": sent,
                "toa_per_packet_ms": round(toa_single, 2),
                "toa_total_ms": round(toa_total, 2)
            }

        return toa_per_node
 
    def _log_vector_values(self):
        self.report_lines.append("\n🎯 SF VECTORS:")
        self.report_lines.extend([f"{v['module']}: {v['value'][:5]}" for v in self.sf_vectors])

        self.report_lines.append("\n🎯 TP VECTORS:")
        self.report_lines.extend([f"{v['module']}: {v['value'][:5]}" for v in self.tp_vectors])

        self.report_lines.append("\n📡 SNIR VECTORS:")
        self.report_lines.extend([f"{v['module']}: {v['value'][:5]}" for v in self.snir_vectors])

        self.report_lines.append("\n📡 RSSI VECTORS:")
        self.report_lines.extend([f"{v['module']}: {v['value'][:5]}" for v in self.rssi_vectors])

    def _log_scalar_summary(self):
        # SCALAR VALUES PER NODE
        self.report_lines.append("\n📈 SCALAR DATA USED FOR PLOTTING:")
        for node_id in sorted(k for k in self.scalar_dict if isinstance(k, int)):
            self.report_lines.append(f"Node {node_id}: {self.scalar_dict[node_id]}")

        # DER, PER, PDR SUMMARY PER NODE
        self.report_lines.append("\n📊 NODE METRICS SUMMARY (DER, PER, PDR):")
        self.report_lines.append("Node  Sent   Recv   PDR      PER      DER     ")
        self.report_lines.append("----------------------------------------------")
        for node in sorted(self.data_error_rate_per_node, key=lambda x: x["node_id"]):
            node_id = node["node_id"]
            sent = node["sent"]
            recv = node["received"]
            pdr = next((x["pdr"] for x in self.packet_delivery_ratio_per_node if x["node_id"] == node_id), 0)
            per = next((x["per"] for x in self.packet_error_rate_per_node if x["node_id"] == node_id), 0)
            der = node["data_error_rate"]
            self.report_lines.append(f"{node_id:<5} {sent:<6} {recv:<6} {pdr:<8.4f} {per:<8.4f} {der:<8.4f}")

        # FINAL SF / TP
        self.report_lines.append("\n📶 FINAL SPREADING FACTOR (SF) PER NODE:")
        for node_id in sorted(self.final_sf):
            self.report_lines.append(f"Node {node_id}: SF{self.final_sf[node_id]}")

        self.report_lines.append("\n📶 FINAL TRANSMISSION POWER (TP) PER NODE:")
        for node_id in sorted(self.final_tp):
            self.report_lines.append(f"Node {node_id}: TP{self.final_tp[node_id]}")

        # DER scalars
        self.report_lines.append("\n📊 DATA EXTRACTION RATE (DER) METRICS")

        # Server scalar
        self.report_lines.append("\n🔧 Overall DER (from server scalar):")
        for s in self.server_der_scalars:
            self.report_lines.append(f"{s['name']}: {float(s['value']):.5f}")

        # Per gateway
        self.report_lines.append("\n📡 Data Extraction Rate per Gateway:")
        if self.data_extraction_rate_per_gateway:
            for gw_id in sorted(self.data_extraction_rate_per_gateway):
                val = self.data_extraction_rate_per_gateway[gw_id]
                self.report_lines.append(f"Gateway {gw_id}:  {val:.5f}")
        else:
            self.report_lines.append("None found.")

        # Per SF
        self.report_lines.append("\n📶 Data Extraction Rate per Spreading Factor (SF):")
        if self.data_extraction_rate_per_sf:
            for sf in sorted(self.data_extraction_rate_per_sf):
                val = self.data_extraction_rate_per_sf[sf]
                self.report_lines.append(f"SF{sf}:  {val:.5f}")
        else:
            self.report_lines.append("None found.")
    
        self.report_lines.append("\n📥 PACKETS RECEIVED PER GATEWAY:")
        if self.packets_received_per_gateway:
            for gw_id in sorted(self.packets_received_per_gateway):
                count = self.packets_received_per_gateway[gw_id]
                self.report_lines.append(f"Gateway {gw_id}: {count}")
        else:
            self.report_lines.append("None found.")
    
        # TIME ON AIR PER NODE
        self.report_lines.append("\n⏱️ TIME ON AIR PER NODE (in ms):")
        toa_data = self.calculate_toa_per_node()
        total_network_toa = 0.0

        for node_id, values in sorted(toa_data.items()):
            self.report_lines.append(
                f"Node {node_id}: SF{values['sf']}, Sent={values['sent']}, ToA/Packet={values['toa_per_packet_ms']}ms, ToA Total={values['toa_total_ms']}ms"
            )
            total_network_toa += values["toa_total_ms"]

        self.report_lines.append(f"\n📊 TOTAL NETWORK TIME ON AIR: {round(total_network_toa, 2)} ms")


    def split_vector_by_node(self, vec, num_nodes):
        values = vec.get("value", [])
        chunk_size = len(values) // num_nodes
        return {
            node_id: values[node_id * chunk_size: (node_id + 1) * chunk_size]
            for node_id in range(num_nodes)
        }

    def _get_node_id_from_module(self, _, module):
        match = re.search(r"loRaNodes\[(\d+)\]", module)
        return int(match.group(1)) if match else module

    def _get_index_id(self, index, _):
        return index

    def _sort_into_scalars(self):
        for scalar in self.scalars:
            name = scalar["name"]
            module = scalar["module"]

            node_id = self._extract_node_or_gateway_number(module, "loRaNodes")
            gateway_id = self._extract_node_or_gateway_number(module, "loRaGW")

            if node_id is not None:
                entity_type = 'node'
                entity_id = node_id
            elif gateway_id is not None:
                entity_type = 'gateway'
                entity_id = gateway_id
            elif "networkServer" in module:
                entity_type = 'server'
                entity_id = None
            else:
                entity_type = 'unknown'
                entity_id = None

            self.scalar_dict[name].append({
                "module": module,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "value": scalar["value"]
            })

    def _extract_node_or_gateway_number(self, module, prefix):
        import re
        match = re.search(rf"{prefix}\\[(\\d+)\\]", module)
        return int(match.group(1)) if match else None

    def calculate_data_error_rate(self):
        results = []
        received = {
            int(name.split(" ")[-1]): entries[0]["value"]
            for name, entries in self.scalar_dict.items()
            if isinstance(name, str) and name.startswith("numReceivedFromNode ")
        }

        sent_entries = self.scalar_dict.get("sentPackets", [])
        if not sent_entries:
            print("❗️Missing 'sentPackets' data in scalar_dict.")
        if not received:
            print("❗️Missing 'numReceivedFromNode X' data in scalar_dict.")

        for nid in received:
            recv = received[nid]
            sent_entry = next((e for e in sent_entries if str(nid) in e["module"]), None)
            if sent_entry is None:
                print(f"⚠️ Node {nid}: No matching sentPackets entry found.")
                continue
            sent = sent_entry["value"]
            if sent == 0:
                print(f"⚠️ Node {nid}: Sent = 0, skipping.")
                continue
            der = (sent - recv) / sent
            results.append({"node_id": nid, "sent": sent, "received": recv, "data_error_rate": der})
        return results

    def calculate_pdr(self):
        results = []
        received = {
            int(name.split(" ")[-1]): entries[0]["value"]
            for name, entries in self.scalar_dict.items()
            if name.startswith("numReceivedFromNode ")
        }
        for entry in self.scalar_dict.get("sentPackets", []):
            if entry["entity_type"] == "node":
                nid = entry["entity_id"]
                sent = entry["value"]
                recv = received.get(nid, 0)
                pdr = recv / sent if sent else 0.0
                results.append({"node_id": nid, "sent": sent, "received": recv, "pdr": pdr})
        return results

    def calculate_per(self):
        results = []
        received = {
            int(name.split(" ")[-1]): entries[0]["value"]
            for name, entries in self.scalar_dict.items()
            if name.startswith("numReceivedFromNode ")
        }
        for entry in self.scalar_dict.get("sentPackets", []):
            if entry["entity_type"] == "node":
                nid = entry["entity_id"]
                sent = entry["value"]
                recv = received.get(nid, 0)
                per = (sent - recv) / sent if sent else 0.0
                results.append({"node_id": nid, "sent": sent, "received": recv, "per": per})
        return results

    def extract_last_sf_per_node(self):
        return {
            e["entity_id"]: e["value"]
            for e in self.scalar_dict.get("finalSF", [])
            if e["entity_type"] == "node"
        }

    def extract_last_tp_per_node(self):
        return {
            e["entity_id"]: e["value"]
            for e in self.scalar_dict.get("finalTP", [])
            if e["entity_type"] == "node"
        }

    def get_data_extraction_rate_scalars(self):
        result = []
        for name, scalars in self.scalar_dict.items():
            if name.startswith("DER"):
                for s in scalars:
                    result.append({
                        "name": name,
                        "entity_type": s["entity_type"],
                        "entity_id": s["entity_id"],
                        "value": s["value"]
                    })
        return result
    
    def plot_data_error_rate(self):
        raw_data = self.calculate_data_error_rate()

        if not raw_data:
            print("⚠️ No data to plot for DER. Skipping plot generation.")
            return

        # Construim un dicționar complet cu toți nodurile de la 0 la 9
        max_node_id = 9
        der_dict = {entry["node_id"]: entry["data_error_rate"] for entry in raw_data}
        data_complete = [{"node_id": i, "data_error_rate": der_dict.get(i, 0.0)} for i in range(max_node_id + 1)]

        node_ids = [entry["node_id"] for entry in data_complete]
        der_values = [entry["data_error_rate"] for entry in data_complete]
        labels = [str(nid) for nid in node_ids]

        x_pos = range(len(node_ids))

        plt.figure(figsize=(10, 5))  # opțional, să ai mai mult spațiu între bare
        bars = plt.bar(x_pos, der_values, color=cm.tab20.colors[:len(node_ids)])
        plt.xticks(x_pos, labels)
        plt.title("Data Error Rate per Node")
        plt.xlabel("Node ID")
        plt.ylabel("Data Error Rate")
        plt.grid(True, axis='y')

        for i, bar in enumerate(bars):
            height = bar.get_height()
            plt.text(bar.get_x() + bar.get_width()/2.0, height, f"{der_values[i]:.2f}", ha='center', va='bottom', fontsize=8)

        plot_path = os.path.join(self.output_path, "data_error_rate_per_node.png")
        plt.savefig(plot_path)
        print(f"✅ DER plot saved to: {plot_path}")
        plt.close()

    def get_all_metrics(self):
        return {
            "sf_vectors": self.sf_vectors,
            "tp_vectors": self.tp_vectors,
            "snir_vectors": self.snir_vectors,
            "rssi_vectors": self.rssi_vectors,
            "final_sf": self.extract_last_sf_per_node(),
            "final_tp": self.extract_last_tp_per_node(),
            "data_error_rate_per_node ": self.calculate_data_error_rate(),
            "packet_delivery_ratio_per_node ": self.calculate_pdr(),
            "packet_error_rate_per_node": self.calculate_per(),
            "server_der_scalars ": self.get_data_extraction_rate_scalars(),
        }

class MultiScenarioAnalyzer:
    def __init__(self, scenario_folders):
        self.scenario_folders = scenario_folders
        self.results = {}

    def run_all(self):
        for folder in self.scenario_folders:
            if not os.path.isdir(folder):
                print(f"❌ Folder does not exist: {folder}")
                continue

            prefixes = self._get_file_prefixes(folder)
            if not prefixes:
                print(f"⚠️ No valid *_app.json files found in {folder}.")
                continue

            for prefix in prefixes:
                print(f"\n📂 Processing scenario: {folder}, set: {prefix}")
                output_path = os.path.join(folder, "plots", prefix)
                os.makedirs(output_path, exist_ok=True)
                extractor = LoRaMetricExtractor(input_path=folder, output_path=output_path, prefix=prefix)
                extractor.load_data()
                extractor.plot_data_error_rate()
                metrics = extractor.get_all_metrics()
                scenario_id = f"{os.path.basename(folder)}__{prefix}"
                self.results[scenario_id] = metrics

    def _get_file_prefixes(self, folder):
        files = os.listdir(folder)
        app_files = [f for f in files if f.endswith('_app.json')]
        prefixes = set(f.replace('_app.json', '') for f in app_files)
        return sorted(prefixes)

    def get_results(self):
        return self.results

if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.abspath(os.path.join(base_dir, ".."))  # results_and_analysis

    # Căutăm recursiv în toate subfolderele care conțin "export_json"
    scenario_folders = []
    for root, dirs, files in os.walk(parent_dir):
        for d in dirs:
            if d.startswith("export_json"):
                scenario_folders.append(os.path.join(root, d))

    print('📂 Listă directoare de scenarii găsite:')
    for folder in scenario_folders:
        print(f'📁 {folder}')

    # 🔥 ȘTERGERE folder "plots" din fiecare "export_json_*"
    for folder in scenario_folders:
        plots_folder = os.path.join(folder, "plots")
        if os.path.exists(plots_folder):
            print(f"🧹 Ștergere folder: {plots_folder}")
            shutil.rmtree(plots_folder)

    # 📈 Rulează analiza pentru fiecare scenariu/prefix
    for folder in scenario_folders:
        for prefix_file in glob.glob(os.path.join(folder, "*_app.json")):
            prefix = os.path.basename(prefix_file).replace("_app.json", "")
            output_path = os.path.join(folder, "plots", prefix)
            extractor = LoRaMetricExtractor(folder, output_path, prefix)
            extractor.load_data()
            extractor.plot_data_error_rate()

