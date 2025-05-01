# Import necessary libraries
import json
import re
import math
from collections import defaultdict
import matplotlib.pyplot as plt
import numpy as np
import os
import glob
from io import StringIO
import sys
from scenarios import ScenarioMetrics
from scipy.interpolate import make_interp_spline

class LoRaSimulationAnalyzer:
    """
    A class to analyze LoRa network simulation data from OMNeT++
    """
    
    # Constants
    EXPORT_DIR = "plots"
    NODE_PREFIX = 'LoRaNetworkTest.loRaNodes'
    GW_PREFIX = 'LoRaNetworkTest.loRaGW'
    SERVER_PREFIX = 'LoRaNetworkTest.networkServer.app[0]'
    REQUIRED_SNR_PER_SF = {
                            7: -7.5,
                            8: -10,
                            9: -12.5,
                            10: -15,
                            11: -17.5,
                            12: -20
                        }
    
    def __init__(self, num_nodes=10, dmargin=15):
        """
        Initialize the analyzer with simulation data
        
        Args:
            num_nodes (int): Number of LoRa nodes in the simulation
        """
        self.num_nodes = num_nodes
        self.cmap = plt.colormaps.get_cmap("tab10").resampled(num_nodes)
        self.node_colors = {i: self.cmap(i) for i in range(num_nodes)}
        
        # Initialize data containers
        self.all_data = None
        self.histogram_data = None
        self.all_scalars_data = None
        self.parameters = None
        self.scalars = None
        self.vectors = None
        self.histograms = None
        
        # Categorized data
        self.tp_vectors = []
        self.sf_vectors = []
        self.snir_vectors = []
        self.rssi_vectors = []
        self.rssi_histograms = []
        self.scalar_dict = None
        self.snr_margin_vectors = []
        
        # Simulation parameters
        self.sim_time = None
        self.payload_size = None
        self.bandwidth_khz = None
        self.metrics_summary = None

        self.D_MARGIN = dmargin  # Default is 15 dB

    def plot_spreading_factor_distribution(self):
        """
        Plot Spreading Factor (SF) distribution per node using OMNeT++-style binning from sf_vectors.
        """
        sf_values_by_node = defaultdict(list)

        for vec in self.sf_vectors:
            values = vec.get("value", [])
            if not values:
                continue

            module = vec.get("module", "")
            node_id = self._extract_node_or_gateway_number(module, self.NODE_PREFIX)
            if node_id is not None:
                sf_values_by_node[node_id].extend(values)

        if not sf_values_by_node:
            print("⚠️ No SF vector data found in sf_vectors.")
            return

        plt.figure(figsize=(12, 6))
        bins = np.arange(6.5, 13.5, 1)  # SF 7 to 12 inclusive

        for node_id, values in sf_values_by_node.items():
            plt.hist(
                values,
                bins=bins,
                alpha=0.6,
                edgecolor='black',
                label=f"Node {node_id}"
            )

        plt.xlabel("Spreading Factor (SF)")
        plt.ylabel("Occurrences")
        plt.title("Spreading Factor Distribution per Node")
        plt.xticks(np.arange(7, 13))
        plt.legend()
        plt.grid(True)
        plt.tight_layout()
        self._export_plot("sf_distribution.jpeg")
        plt.close()
    
    def compute_metrics_summary(self, scenario_name):
        from scenarios import ScenarioMetrics

        metrics = ScenarioMetrics(scenario_name)
        metrics.analyzer_ref = self  # So we can use analyzer methods later

        # Store maps
        metrics.pdr_map = {
            entry["entity_id"]: entry["value"]
            for entry in self.calculate_pdr()
            if entry.get("entity_type") == "node" and entry.get("entity_id") is not None
        }


        metrics.per_map = self.calculate_per()

        # Extract DER scalars per node (not a map, but can be structured if needed)
        der_scalars = self.get_data_extraction_rate_scalars()
        metrics.der_per_node = {
            scalar["entity_id"]: scalar["value"]
            for scalar in der_scalars
            if scalar["entity_type"] == "node" and scalar["entity_id"] is not None
        }

        metrics.energy_per_delivered = self.calculate_energy_per_packet()
        metrics.toa_map = {
            entry["node_id"]: entry["ToA_sec"]
            for entry in self.calculate_toa_per_node()
        }
        metrics.sf_map = self.extract_last_sf_per_node()
        metrics.tp_map = self.extract_last_tp_per_node()
        metrics.jain_index = self.calculate_jains_fairness_index()
        metrics.throughput = self.calculate_throughput()["throughput_bps"]
        
        # Packet Sent Map (custom lookup)
        metrics.packet_sent_map = {
            entry["entity_id"]: entry["value"]
            for entry in self.scalar_dict.get("sentPackets", [])
            if entry["entity_type"] == "node" and entry["entity_id"] is not None
        }

        # Collision Count Map (custom lookup)
        metrics.collision_count_map = {
            entry["entity_id"]: entry["value"]
            for entry in self.scalar_dict.get("collisionCount", [])
            if entry["entity_type"] == "node" and entry["entity_id"] is not None
        }

        # adrCommandCount, retransmissionCount, and packetDropQueueOverflow (custom lookup)
        metrics.adr_command_count_map = {
            entry["entity_id"]: entry["value"]
            for entry in self.scalar_dict.get("adrCommandCount", [])
            if entry["entity_type"] == "node" and entry["entity_id"] is not None
        }
        metrics.retransmission_count_map = {
            entry["entity_id"]: entry["value"]
            for entry in self.scalar_dict.get("retransmissionCount", [])
            if entry["entity_type"] == "node" and entry["entity_id"] is not None
        }
        metrics.queue_overflow_drops = {
            entry["entity_id"]: entry["value"]
            for entry in self.scalar_dict.get("packetDropQueueOverflow:count", [])
            if entry["entity_type"] == "node" and entry["entity_id"] is not None
        }

        metrics.data_error_rate_map = {
            entry["node_id"]: entry["data_error_rate"]
            for entry in self.calculate_data_error_rate()
        }
        metrics.data_extraction_rate_per_gateway = self.get_data_extraction_rate_per_gateway()

        # Raw signal values
        metrics.snr_map = {
            entry["entity_id"]: entry["value"]
            for entry in self.scalar_dict.get("snr", [])
            if entry["entity_type"] == "node" and entry["entity_id"] is not None
        }
        metrics.snir_map = compute_average_signal_map_by_order(metrics.snir_vectors)
        metrics.rssi_map = compute_average_signal_map_by_order(metrics.rssi_vectors)

        # Raw vectors
        metrics.tp_vectors = self.tp_vectors
        metrics.sf_vectors = self.sf_vectors
        metrics.snir_vectors = self.snir_vectors
        metrics.rssi_vectors = self.rssi_vectors
        metrics.snr_margin_vectors = self.snr_margin_vectors  # ✅

        self.metrics_summary = metrics
        return metrics

    def load_data(self, all_apps_path, all_histograms_path, all_scalars_path, all_parameters_path):
        """
        Load all simulation data from JSON files
        """
        # Load all application data
        with open(all_apps_path) as f:
            self.all_data = json.load(f)
        
        # Load histogram data
        with open(all_histograms_path) as f:
            self.histogram_data = json.load(f)
        
        # Load scalar data
        with open(all_scalars_path) as f:
            self.all_scalars_data = eval("\n".join(line for line in f if not line.strip().startswith("#")))
        
        # Load parameters
        self.parameters = self._load_flat_parameters(all_parameters_path)
        
        # Extract run data from the first experiment
        run_id = next(iter(self.all_data.keys()))
        self.vectors = self.all_data[run_id]["vectors"]
        self.histograms = self.histogram_data[run_id]["histograms"]
        self.scalars = self.all_scalars_data[run_id]["scalars"]
        
        # Extract key simulation parameters
        self.sim_time = float(self.parameters.get("sim-time-limit", "1600000s").rstrip("s"))
        self.payload_size = int(self.parameters.get("**.payloadSize", 20))
        self.bandwidth_khz = int(self.parameters.get("**.bandwidth", "125kHz").rstrip("kHz"))
        
        # Sort the data
        self._sort_into_vectors()
        self._sort_into_histograms()
        self.scalar_dict = self._sort_into_scalars()
        
        return self
    
    def _load_flat_parameters(self, filepath):
        """
        Load and flatten parameter data from a JSON file, including both config and parameters sections.
        """
        with open(filepath) as f:
            raw = f.read()
            if raw.strip().startswith("#"):
                raw = "\n".join([line for line in raw.splitlines() if not line.strip().startswith("#")])
            param_data = eval(raw)

        run_key = next(iter(param_data))
        entry = param_data[run_key]

        parameters = {}

        # Include from "config"
        for config_entry in entry.get("config", []):
            parameters.update(config_entry)

        # Include from "parameters"
        for param_entry in entry.get("parameters", []):
            name = param_entry.get("name")
            value = param_entry.get("value")
            if name and value is not None:
                parameters[name] = value

        return parameters
    
    def _extract_node_or_gateway_number(self, module_name: str, node_prefix: str = "loRaNodes") -> int | None:
        """
        Extract node or gateway ID from full module name based on prefix.
        E.g., from "LoRaNetworkTest.loRaNodes[2].LoRaNic.mac" it will return 2.
        """
        import re

        # Look for 'loRaNodes[<id>]' or 'gateways[<id>]' inside any module path
        pattern = rf"{re.escape(node_prefix)}\[(\d+)\]"
        match = re.search(pattern, module_name)
        if match:
            return int(match.group(1))
        return None

    def _extract_node_or_gateway_number_for_collisions(self, module, prefix):
        import re
        match = re.search(rf"{re.escape(prefix)}(\d+)", module)
        return int(match.group(1)) if match else None

    def extract_node_id(self, module_name):
        return self._extract_node_or_gateway_number(module_name, "loRaNodes")
    
    def _sort_into_vectors(self):
        """
        Sort vectors into categories
        """
        self.tp_vectors = []
        self.sf_vectors = []
        self.snir_vectors = []
        self.rssi_vectors = []
        self.snr_margin_vectors = []  # ✅ Added for SNR Margin

        for vec in self.vectors:
            name = vec.get("name", "").lower()
            if 'tp vector' in name:
                self.tp_vectors.append(vec)
            elif 'sf vector' in name:
                self.sf_vectors.append(vec)
            elif 'snir' in name:
                self.snir_vectors.append(vec)
            elif 'rssi' in name:
                self.rssi_vectors.append(vec)
            elif 'snrmargin' in name.replace(" ", ""):
                self.snr_margin_vectors.append(vec)

        print(f'SNR Margin Vectors: {[self._extract_node_or_gateway_number(vec["module"], self.NODE_PREFIX) for vec in self.snr_margin_vectors]}')
    
    def plot_data_error_rate_per_node(self):
        """
        Plot Data Error Rate (DER) per node for the current scenario.
        """
        if not self.metrics_summary or not self.metrics_summary.data_error_rate_map:
            print("⚠️ No data error rate info for this scenario.")
            return

        scenario_name = self.metrics_summary.name
        print(f"📊 Plotting Data Error Rate per Node for scenario: {scenario_name}")

        data_error = self.metrics_summary.data_error_rate_map
        node_ids = sorted(data_error.keys())
        error_rates = [data_error[node_id] for node_id in node_ids]

        plt.figure(figsize=(10, 6))
        bars = plt.bar(node_ids, error_rates, color='tomato', edgecolor='black')
        plt.xlabel("Node ID")
        plt.ylabel("Data Error Rate")
        plt.title(f"Data Error Rate per Node - {scenario_name}")
        plt.ylim(0, 1.0)
        plt.grid(axis='y', linestyle='--', alpha=0.7)
        plt.xticks(node_ids)
        plt.tight_layout()

        # Annotate bars with DER values
        for bar, value in zip(bars, error_rates):
            height = bar.get_height()
            plt.text(
                bar.get_x() + bar.get_width() / 2,
                height + 0.01,
                f"{value:.2f}",
                ha='center',
                va='bottom',
                fontsize=9,
                fontweight='bold'
            )

        self._export_plot("data_error_rate_per_node.jpeg")
        plt.close()

    def _sort_into_histograms(self):
        """
        Sort histograms into categories
        """
        self.rssi_histograms = []
        
        for hist in self.histograms:
            if 'receivedRSSI' in hist['name']:
                self.rssi_histograms.append(hist)
        
        self.rssi_histograms.sort(key=lambda h: h['name'])
    
    def _sort_into_scalars(self):
        """
        Sort scalars into a dictionary by name
        """
        scalar_dict = defaultdict(list)
        
        for scalar in self.scalars:
            scalar_name = scalar["name"]
            module_name = scalar["module"]

            # Determine if scalar belongs to node, gateway, or server
            node_id = self._extract_node_or_gateway_number(module_name, self.NODE_PREFIX)
            gateway_id = self._extract_node_or_gateway_number(module_name, self.GW_PREFIX)

            if node_id is not None:
                entity_type = 'node'
                entity_id = node_id
            elif gateway_id is not None:
                entity_type = 'gateway'
                entity_id = gateway_id
            elif self.SERVER_PREFIX in module_name:
                entity_type = 'server'
                entity_id = None
            else:
                entity_type = 'unknown'
                entity_id = None

            scalar_dict[scalar_name].append({
                "module": module_name,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "value": scalar["value"]
            })

        # Sort scalar entries based on entity type
        for scalar_name, scalar_list in scalar_dict.items():
            scalar_list.sort(key=lambda x: (
                0 if x["entity_type"] == 'node' else 1,
                0 if x["entity_type"] == 'gateway' else 1,
                0 if x["entity_id"] is None else x["entity_id"]
            ))

        return scalar_dict
    
    def get_data_extraction_rate_scalars(self):
        """
        Get Data Extraction Rate (DER) scalars per Spreading Factor
        """
        der_scalars = []
        for scalar_name, scalar_list in self.scalar_dict.items():
            if scalar_name.startswith('DER'):
                for scalar in scalar_list:
                    der_scalars.append({
                        'name': scalar_name,
                        'entity_type': scalar['entity_type'],
                        'entity_id': scalar['entity_id'],
                        'value': scalar['value']
                    })
        return der_scalars
    
    def calculate_pdr(self):
        """
        Calculate Packet Delivery Ratio per node
        """
        pdr_per_node = []

        # Create lookup for received packets
        received_lookup = {}
        for name, entries in self.scalar_dict.items():
            if name.startswith("numReceivedFromNode "):
                node_id = int(name.split(" ")[-1])
                received_lookup[node_id] = entries[0]["value"]

        # Calculate PDR for each node
        for sent_scalar in self.scalar_dict.get("sentPackets", []):
            if sent_scalar["entity_type"] == "node":
                node_id = sent_scalar["entity_id"]
                sent = sent_scalar["value"]
                received = received_lookup.get(node_id, 0)
                pdr = received / sent if sent > 0 else 0.0

                pdr_per_node.append({
                    "node_id": node_id,
                    "sent": sent,
                    "received": received,
                    "pdr": pdr
                })

        return pdr_per_node
    
    def calculate_per(self):
        """
        Calculate Packet Error Rate per node (also Frame Erasure Rate)
        """
        per_per_node = []

        # Create lookup for received packets
        received_lookup = {}
        for name, entries in self.scalar_dict.items():
            if name.startswith("numReceivedFromNode "):
                node_id = int(name.split(" ")[-1])
                received_lookup[node_id] = entries[0]["value"]

        # Calculate PER for each node
        for sent_scalar in self.scalar_dict.get("sentPackets", []):
            if sent_scalar["entity_type"] == "node":
                node_id = sent_scalar["entity_id"]
                sent = sent_scalar["value"]
                received = received_lookup.get(node_id, 0)
                per = (sent - received) / sent if sent > 0 else 0.0

                per_per_node.append({
                    "node_id": node_id,
                    "sent": sent,
                    "received": received,
                    "per": per
                })

        return per_per_node
    
    def calculate_energy_per_packet(self):
        """
        Calculate energy consumed per successfully received packet per node (in mJ)
        """
        energy_efficiency = []

        # Create lookup for received packets
        received_lookup = {}
        for name, entries in self.scalar_dict.items():
            if name.startswith("numReceivedFromNode "):
                node_id = int(name.split(" ")[-1])
                received_lookup[node_id] = entries[0]["value"]

        # Calculate energy per packet for each node
        for energy_scalar in self.scalar_dict.get("totalEnergyConsumed", []):
            if energy_scalar["entity_type"] == "node":
                node_id = energy_scalar["entity_id"]
                total_energy = energy_scalar["value"]  # in mJ
                received = received_lookup.get(node_id, 0)

                epp = total_energy / received if received > 0 else float('inf')

                energy_efficiency.append({
                    "node_id": node_id,
                    "energy_consumed_mJ": total_energy,
                    "received": received,
                    "energy_per_packet_mJ": epp
                })

        return energy_efficiency
    
    def calculate_data_error_rate(self):
        """
        Calculate Data Error Rate per node
        """
        der_error_rates = []

        # Create lookup for received packets
        received_lookup = {}
        for name, entries in self.scalar_dict.items():
            if name.startswith("numReceivedFromNode "):
                node_id = int(name.split(" ")[-1])
                received_lookup[node_id] = entries[0]["value"]

        # Calculate data_error_rate for each node
        for sent_scalar in self.scalar_dict.get("sentPackets", []):
            if sent_scalar["entity_type"] == "node":
                node_id = sent_scalar["entity_id"]
                sent_packets = sent_scalar["value"]
                received_packets = received_lookup.get(node_id, 0)

                data_error_rate  = (sent_packets - received_packets) / sent_packets if sent_packets > 0 else 0.0

                der_error_rates.append({
                    "node_id": node_id,
                    "sent": sent_packets,
                    "received": received_packets,
                    "data_error_rate": data_error_rate 
                })

        return der_error_rates
    
    def calculate_jains_fairness_index(self, pdr_results=None):
        """
        Calculate Jain's Fairness Index based on PDR per node
        
        Args:
            pdr_results: PDR results from calculate_pdr() or None to calculate them
        
        Returns:
            float: Jain's Fairness Index (0-1)
        """
        if pdr_results is None:
            pdr_results = self.calculate_pdr()
            
        pdr_values = [entry["pdr"] for entry in pdr_results]
        n = len(pdr_values)
        numerator = sum(pdr_values) ** 2
        denominator = n * sum(p ** 2 for p in pdr_values)
        fairness_index = numerator / denominator if denominator != 0 else 0
        
        return fairness_index
    
    def calculate_throughput(self):
        """
        Calculate network throughput: total bits received / simulation time
        
        Returns:
            float: Throughput in bits per second
        """
        packet_size_bits = self.payload_size * 8

        total_received_packets = 0
        for name, entries in self.scalar_dict.items():
            if name.startswith("numReceivedFromNode "):
                total_received_packets += entries[0]["value"]

        total_bits = total_received_packets * packet_size_bits
        throughput_bps = total_bits / self.sim_time if self.sim_time > 0 else 0

        return {
            "total_received_packets": total_received_packets,
            "payload_size_bytes": self.payload_size,
            "simulation_time_s": self.sim_time,
            "throughput_bps": throughput_bps
        }
    
    def calculate_toa_per_node(self):
        """
        Estimate Time on Air per node
        
        Returns:
            list: Time on Air results per node
        """
        bw_str = self.parameters.get("**.loRaNodes[*].**initialLoRaBW", "125 kHz")
        cr_str = self.parameters.get("**.loRaNodes[*].**initialLoRaCR", "4")
        pl_str = self.parameters.get("**.payloadSize", "20")
        preamble_str = self.parameters.get("**.preambleLength", "8")

        # Parse bandwidth
        try:
            BW_kHz = int("".join(filter(str.isdigit, bw_str)))
            BW = BW_kHz * 1000
        except:
            BW = 125000  # default 125 kHz in Hz

        # Parse coding rate
        try:
            CR = int(cr_str)
        except:
            CR = 4  # default CR 4/5

        # Parse payload size
        try:
            PL = int(pl_str)
        except:
            PL = 20  # default 20 bytes

        # Parse preamble length
        try:
            preamble_len = int(preamble_str)
        except:
            preamble_len = 8  # default 8 symbols

        toa_results = []

        # Calculate ToA for each node using its final SF
        for sf_scalar in self.scalar_dict.get("finalSF", []):
            node_id = sf_scalar["entity_id"]
            SF = int(sf_scalar["value"])

            # Calculate symbol duration
            symbol_duration = (2 ** SF) / BW
            
            # Calculate number of payload symbols
            payload_symb_nb = 8 + max(
                math.ceil((8 * PL - 4 * SF + 28 + 16 - 20) / (4 * (SF - 2))) * (CR + 4), 0
            )
            
            # Calculate time components
            preamble_time = (preamble_len + 4.25) * symbol_duration
            payload_time = payload_symb_nb * symbol_duration
            toa = preamble_time + payload_time

            toa_results.append({
                "node_id": node_id,
                "SF": SF,
                "ToA_sec": toa
            })

        return toa_results
    
    def print_report(self, output_path=None):
        """
        Generate and print a comprehensive report. Also save it to a file if output_path is provided.
        """
        output = StringIO()
        original_stdout = sys.stdout
        sys.stdout = output  # Redirect print to buffer

        try:
            self._print_separator("📦 VECTOR IDS")
            print("TP_VECTORS IDs:", [self._extract_node_or_gateway_number(vec['module'], self.NODE_PREFIX) for vec in self.tp_vectors])
            print("SF_VECTORS IDs:", [self._extract_node_or_gateway_number(vec['module'], self.NODE_PREFIX) for vec in self.sf_vectors])
            print("SNIR_VECTORS IDs:", [self._extract_node_or_gateway_number(vec['module'], self.NODE_PREFIX) for vec in self.snir_vectors])

            self._print_separator("📊 HISTOGRAMS")
            print("Sorted RSSI histograms:", [hist['name'] for hist in self.rssi_histograms])

            self._print_separator("📡 DATA EXTRACTION RATE (PER SF)")
            for der in self.get_data_extraction_rate_scalars():
                ent = der['entity_type'].capitalize()
                if der['entity_id']:
                    ent += f" {der['entity_id']}"
                print(f"{der['name']} ({ent}): {der['value']}")

            self._print_separator("📉 DATA ERROR RATE (PER NODE)")
            for entry in self.calculate_data_error_rate():
                print(f"Node {entry['node_id']}: Data Error Rate = {entry['data_error_rate']:.4f} (Sent = {entry['sent']}, Received = {entry['received']})")

            self._print_separator("📦 PACKET DELIVERY RATIO (PDR PER NODE)")
            for entry in self.calculate_pdr():
                print(f"Node {entry['node_id']}: PDR = {entry['pdr']:.4f} (Sent = {entry['sent']}, Received = {entry['received']})")

            self._print_separator("❌ PACKET ERROR RATE / FRAME ERASURE RATE (PER NODE)")
            for entry in self.calculate_per():
                print(f"Node {entry['node_id']}: PER = {entry['per']:.4f} (Sent = {entry['sent']}, Received = {entry['received']})")

            self._print_separator("🔋 ENERGY PER RECEIVED PACKET (mJ PER NODE)")
            for entry in self.calculate_energy_per_packet():
                print(f"Node {entry['node_id']}: Energy = {entry['energy_consumed_mJ']:.2f} mJ, "
                    f"Received = {entry['received']}, Energy/Packet = {entry['energy_per_packet_mJ']:.4f} mJ")

            self._print_separator("⚖️ JAIN'S FAIRNESS INDEX (BASED ON PDR)")
            print(f"Jain's Fairness Index: {self.calculate_jains_fairness_index():.4f}")

            self._print_separator("📶 NETWORK THROUGHPUT")
            t = self.calculate_throughput()
            print(f"Total Received Packets: {t['total_received_packets']}")
            print(f"Payload Size: {t['payload_size_bytes']} bytes")
            print(f"Simulation Time: {t['simulation_time_s']} s")
            print(f"Throughput: {t['throughput_bps']:.2f} bits per second")

            self._print_separator("🕒 TIME ON AIR (ESTIMATED PER NODE)")
            for entry in self.calculate_toa_per_node():
                print(f"Node {entry['node_id']}: SF={entry['SF']}, ToA = {entry['ToA_sec']*1000:.2f} ms")

            self._print_separator("📶 FINAL SF & TP PER NODE")
            sf_map = self.extract_last_sf_per_node()
            tp_map = self.extract_last_tp_per_node()
            for node in sorted(set(sf_map) | set(tp_map)):
                print(f"Node {node}: SF = {sf_map.get(node, 'N/A')}, TP = {tp_map.get(node, 'N/A')}")

            self._print_separator("📉 PACKET LOSS BREAKDOWN")

            loss_causes = {
                "RetryLimit": "packetDropRetryLimitReached:count",
                "Sensitivity": "rcvBelowSensitivity",
                "Incorrect": "packetDropIncorrectlyReceived:count",
                "NotAddressed": "packetDropNotAddressedToUs:count",
                "QueueOverflow": "packetDropQueueOverflow:count",
                "Collision": "packetDropCollision:count",
                "MACBusy": "packetDropMACBusy:count",
                "DutyCycleLimit": "packetDropDutyCycleLimit:count",
                "GatewayBusy": "packetDropGatewayBusy:count",
                "GatewayQueueOverflow": "packetDropGatewayQueueOverflow:count",
            }

            # Inițializări
            loss_summary = defaultdict(lambda: {**{k: 0 for k in loss_causes}, "Unattributed": 0})
            sent_packets = defaultdict(int)
            received_per_node = defaultdict(int)

            # Parcurgem scalarii
            for scalar in self.scalars:
                module = scalar.get("module", "")
                name = scalar.get("name", "")
                value = scalar.get("value", 0)

                node_id = self._extract_node_or_gateway_number(module, node_prefix="loRaNodes")
                if node_id is not None:
                    # Pachete trimise
                    if name == "sentPackets":
                        sent_packets[node_id] += value

                    # Cauze explicite
                    for cause_name, scalar_key in loss_causes.items():
                        if name == scalar_key:
                            loss_summary[node_id][cause_name] += value

            # Calculăm total pachete recepționate corect de gateway-uri (toate venind de la Node 0 în acest caz)
            # Dacă vei avea mai mulți noduri, va trebui să identifici pachetele pe baza unei etichete (ex: srcId)
            total_gw_received = 0
            for scalar in self.scalars:
                if scalar.get("name", "") == "LoRaGWRadioReceptionFinishedCorrect:count":
                    total_gw_received += scalar.get("value", 0)

            # Atribuim recepțiile doar lui Node 0
            for node_id in sent_packets:
                received_per_node[node_id] = total_gw_received

            # Calculăm pierderile neatribuite
            for node_id in sorted(sent_packets):
                total_sent = sent_packets[node_id]
                total_received = received_per_node[node_id]
                explained_loss = sum(loss_summary[node_id][k] for k in loss_causes)
                total_lost = total_sent - total_received
                loss_summary[node_id]["Unattributed"] = max(0, total_lost - explained_loss)

            # Afișare rezultat
            total_all = 0
            for node in sorted(loss_summary):
                node_loss = loss_summary[node]
                total_node = sum(node_loss.values())
                total_all += total_node
                print(f"Node {node}: {node_loss} | Total Lost = {total_node}")

            print(f"\nTotal packet losses (all nodes): {total_all}")

        finally:
            sys.stdout = original_stdout

        content = output.getvalue()
        print(content)  # Still print to console

        # === Save to file if path provided
        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(content)
        print(f"Report saved to {output_path}")

    def _print_separator(self, title):
        """
        Print a section separator
        """
        print("\n" + "="*60)
        print(f"{title}")
        print("="*60)

    def plot_pdr_vs_nodes(self, group_by='node'):
        """
        Plot Packet Delivery Ratio vs. Nodes

        Args:
            group_by (str): Group by 'node', 'sf', or 'tp'
        """
        pdr_results = self.calculate_pdr()

        if group_by == 'node':
            # PDR vs Nodes simple bar chart
            nodes = [entry['node_id'] for entry in pdr_results]
            pdr_values = [entry['pdr'] for entry in pdr_results]
            
            plt.figure(figsize=(10, 6))
            bars = plt.bar(nodes, pdr_values, color=[self.node_colors[n] for n in nodes])
            
            plt.xlabel('Node ID')
            plt.ylabel('Packet Delivery Ratio')
            plt.title('PDR per Node')
            plt.ylim(0, 1.1)
            plt.grid(axis='y', linestyle='--', alpha=0.7)
            plt.xticks(nodes)
            
            # Add value labels on top of bars
            for bar in bars:
                height = bar.get_height()
                plt.text(bar.get_x() + bar.get_width()/2., height + 0.02,
                        f'{height:.2f}', ha='center', va='bottom')
            
        elif group_by == 'sf':
            # Group PDR by SF
            sf_lookup = {}
            for sf_scalar in self.scalar_dict.get("finalSF", []):
                if sf_scalar["entity_type"] == "node":
                    sf_lookup[sf_scalar["entity_id"]] = int(sf_scalar["value"])
            
            sf_pdr_map = defaultdict(list)
            for entry in pdr_results:
                node_id = entry['node_id']
                if node_id in sf_lookup:
                    sf = sf_lookup[node_id]
                    sf_pdr_map[sf].append(entry['pdr'])
            
            # Calculate average PDR per SF
            sf_values = sorted(sf_pdr_map.keys())
            avg_pdr = [np.mean(sf_pdr_map[sf]) for sf in sf_values]
            
            plt.figure(figsize=(10, 6))
            bars = plt.bar(sf_values, avg_pdr)
            
            plt.xlabel('Spreading Factor (SF)')
            plt.ylabel('Average Packet Delivery Ratio')
            plt.title('PDR vs SF')
            plt.ylim(0, 1.1)
            plt.grid(axis='y', linestyle='--', alpha=0.7)
            plt.xticks(sf_values)
            
            # Add value labels and node counts
            for i, bar in enumerate(bars):
                height = bar.get_height()
                node_count = len(sf_pdr_map[sf_values[i]])
                plt.text(bar.get_x() + bar.get_width()/2., height + 0.02,
                        f'{height:.2f}\n(n={node_count})', ha='center', va='bottom')
                
        elif group_by == 'tp':
            # Group PDR by transmission power
            tp_lookup = {}
            for tp_scalar in self.scalar_dict.get("finalTP", []):
                if tp_scalar["entity_type"] == "node":
                    tp_lookup[tp_scalar["entity_id"]] = tp_scalar["value"]
            
            tp_pdr_map = defaultdict(list)
            for entry in pdr_results:
                node_id = entry['node_id']
                if node_id in tp_lookup:
                    tp = tp_lookup[node_id]
                    tp_pdr_map[tp].append(entry['pdr'])
            
            # Calculate average PDR per TP
            tp_values = sorted(tp_pdr_map.keys())
            avg_pdr = [np.mean(tp_pdr_map[tp]) for tp in tp_values]
            
            plt.figure(figsize=(10, 6))
            bars = plt.bar(tp_values, avg_pdr)
            
            plt.xlabel('Transmission Power (dBm)')
            plt.ylabel('Average Packet Delivery Ratio')
            plt.title('PDR vs Transmission Power')
            plt.ylim(0, 1.1)
            plt.grid(axis='y', linestyle='--', alpha=0.7)
            plt.xticks(tp_values)
            
            # Add value labels and node counts
            for i, bar in enumerate(bars):
                height = bar.get_height()
                node_count = len(tp_pdr_map[tp_values[i]])
                plt.text(bar.get_x() + bar.get_width()/2., height + 0.02,
                        f'{height:.2f}\n(n={node_count})', ha='center', va='bottom')

        plt.tight_layout()
        plt.show()
        return plt.gcf()

    def plot_energy_consumption(self, group_by='node'):
        """
        Plot energy consumption for nodes
        
        Args:
            group_by (str): Group by 'node' or 'tp'
        """
        energy_results = []
        
        # Get total energy consumed per node
        for energy_scalar in self.scalar_dict.get("totalEnergyConsumed", []):
            if energy_scalar["entity_type"] == "node":
                node_id = energy_scalar["entity_id"]
                total_energy = energy_scalar["value"]  # in mJ
                
                energy_results.append({
                    "node_id": node_id,
                    "energy_consumed_mJ": total_energy
                })
        
        if group_by == 'node':
            # Energy vs Nodes bar chart
            nodes = [entry['node_id'] for entry in energy_results]
            energy_values = [entry['energy_consumed_mJ'] for entry in energy_results]
            
            plt.figure(figsize=(10, 6))
            bars = plt.bar(nodes, energy_values, color=[self.node_colors[n] for n in nodes])
            
            plt.xlabel('Node ID')
            plt.ylabel('Energy Consumed (mJ)')
            plt.title('Energy Consumption per Node')
            plt.grid(axis='y', linestyle='--', alpha=0.7)
            plt.xticks(nodes)
            
            # Add value labels on top of bars
            for bar in bars:
                height = bar.get_height()
                plt.text(bar.get_x() + bar.get_width()/2., height + 1,
                        f'{height:.1f}', ha='center', va='bottom')
        
        elif group_by == 'tp':
            # Group energy by transmission power
            tp_lookup = {}
            for tp_scalar in self.scalar_dict.get("finalTP", []):
                if tp_scalar["entity_type"] == "node":
                    tp_lookup[tp_scalar["entity_id"]] = tp_scalar["value"]
            
            tp_energy_map = defaultdict(list)
            for entry in energy_results:
                node_id = entry['node_id']
                if node_id in tp_lookup:
                    tp = tp_lookup[node_id]
                    tp_energy_map[tp].append(entry['energy_consumed_mJ'])
            
            # Calculate average energy per TP
            tp_values = sorted(tp_energy_map.keys())
            avg_energy = [np.mean(tp_energy_map[tp]) for tp in tp_values]
            
            plt.figure(figsize=(10, 6))
            bars = plt.bar(tp_values, avg_energy)
            
            plt.xlabel('Transmission Power (dBm)')
            plt.ylabel('Average Energy Consumed (mJ)')
            plt.title('Energy Consumption vs Transmission Power')
            plt.grid(axis='y', linestyle='--', alpha=0.7)
            plt.xticks(tp_values)
            
            # Add value labels and node counts
            for i, bar in enumerate(bars):
                height = bar.get_height()
                node_count = len(tp_energy_map[tp_values[i]])
                plt.text(bar.get_x() + bar.get_width()/2., height + 1,
                        f'{height:.1f}\n(n={node_count})', ha='center', va='bottom')
        
        plt.tight_layout()
        plt.show()
        return plt.gcf()

    def plot_collision_rate_vs_density(self, node_grouping=2):
        """
        Plot collision rate vs. node density
        
        Args:
            node_grouping (int): Group nodes into N chunks to simulate different densities
        """
        # Get collision data
        collision_results = []
        
        # Collect packets lost due to collisions and total sent
        for collision_scalar in self.scalar_dict.get("collidedPackets", []):
            if collision_scalar["entity_type"] == "node":
                node_id = collision_scalar["entity_id"]
                collided = collision_scalar["value"]
                
                # Find corresponding sent packets
                sent = 0
                for sent_scalar in self.scalar_dict.get("sentPackets", []):
                    if sent_scalar["entity_type"] == "node" and sent_scalar["entity_id"] == node_id:
                        sent = sent_scalar["value"]
                        break
                
                collision_rate = collided / sent if sent > 0 else 0.0
                
                collision_results.append({
                    "node_id": node_id,
                    "collided": collided,
                    "sent": sent,
                    "collision_rate": collision_rate
                })
        
        # Sort by node ID
        collision_results.sort(key=lambda x: x["node_id"])
        
        # Group nodes to simulate different node densities
        groups = []
        current_group = []
        
        for i, result in enumerate(collision_results):
            current_group.append(result)
            if len(current_group) == node_grouping or i == len(collision_results) - 1:
                # Calculate aggregated collision rate for this group
                total_collided = sum(node["collided"] for node in current_group)
                total_sent = sum(node["sent"] for node in current_group)
                group_collision_rate = total_collided / total_sent if total_sent > 0 else 0.0
                
                groups.append({
                    "nodes": [node["node_id"] for node in current_group],
                    "density": len(current_group),
                    "collision_rate": group_collision_rate
                })
                current_group = []
        
        # Plot results
        plt.figure(figsize=(10, 6))
        
        densities = [g["density"] for g in groups]
        collision_rates = [g["collision_rate"] * 100 for g in groups]  # Convert to percentage
        
        plt.plot(densities, collision_rates, 'o-', markersize=8)
        
        plt.xlabel('Node Density (nodes per group)')
        plt.ylabel('Collision Rate (%)')
        plt.title('Collision Rate vs. Node Density')
        plt.grid(True, linestyle='--', alpha=0.7)
        
        # Add data labels
        for i, (d, cr) in enumerate(zip(densities, collision_rates)):
            node_list = groups[i]["nodes"]
            plt.annotate(f'{cr:.1f}%\n{node_list}', 
                        (d, cr), 
                        xytext=(5, 5),
                        textcoords='offset points')
        
        plt.tight_layout()
        plt.show()
        return plt.gcf()

    def plot_jains_fairness_index(self, metric='pdr'):
        """
        Plot Jain's Fairness Index for different metrics
        
        Args:
            metric (str): Which metric to plot fairness for ('pdr', 'energy', 'toa')
        """
        plt.figure(figsize=(8, 6))
        
        # PDR fairness is always calculated
        pdr_results = self.calculate_pdr()
        jfi_pdr = self.calculate_jains_fairness_index(pdr_results)
        
        # Calculate fairness indices for different metrics
        metrics = []
        fairness_values = []
        
        # PDR fairness
        metrics.append('PDR')
        fairness_values.append(jfi_pdr)
        
        # Energy fairness - calculate JFI using energy per successful packet
        if 'energy' in metric.lower():
            energy_results = self.calculate_energy_per_packet()
            # Filter out infinite values (no packets received)
            energy_values = [entry["energy_per_packet_mJ"] for entry in energy_results 
                            if entry["energy_per_packet_mJ"] != float('inf')]
            
            if energy_values:
                n = len(energy_values)
                # For energy, less consumption is better, so invert values
                # First normalize to [0,1] range
                if max(energy_values) > min(energy_values):
                    norm_energy = [(max(energy_values) - e) / (max(energy_values) - min(energy_values)) 
                                for e in energy_values]
                else:
                    norm_energy = [1.0] * len(energy_values)
                    
                numerator = sum(norm_energy) ** 2
                denominator = n * sum(e ** 2 for e in norm_energy)
                jfi_energy = numerator / denominator if denominator != 0 else 0
                
                metrics.append('Energy')
                fairness_values.append(jfi_energy)
        
        # ToA fairness
        if 'toa' in metric.lower():
            toa_results = self.calculate_toa_per_node()
            toa_values = [entry["ToA_sec"] for entry in toa_results]
            
            if toa_values:
                n = len(toa_values)
                numerator = sum(toa_values) ** 2
                denominator = n * sum(t ** 2 for t in toa_values)
                jfi_toa = numerator / denominator if denominator != 0 else 0
                
                metrics.append('ToA')
                fairness_values.append(jfi_toa)
        
        # Plot the fairness indices
        bars = plt.bar(metrics, fairness_values)
        
        plt.xlabel('Metric')
        plt.ylabel('Jain\'s Fairness Index')
        plt.title('Jain\'s Fairness Index for Different Metrics')
        plt.ylim(0, 1.1)
        plt.grid(axis='y', linestyle='--', alpha=0.7)
        
        # Add value labels
        for bar in bars:
            height = bar.get_height()
            plt.text(bar.get_x() + bar.get_width()/2., height + 0.02,
                    f'{height:.4f}', ha='center', va='bottom')
        
        plt.tight_layout()
        plt.show()
        return plt.gcf()

    def plot_sf_distribution(self):
        """
        Plot the distribution of Spreading Factors assigned to nodes
        """
        # Get SF data
        sf_results = []
        
        # Get SF for each node
        for sf_scalar in self.scalar_dict.get("finalSF", []):
            if sf_scalar["entity_type"] == "node":
                node_id = sf_scalar["entity_id"]
                sf = int(sf_scalar["value"])
                
                sf_results.append({
                    "node_id": node_id,
                    "sf": sf
                })
        
        if not sf_results:
            print("No SF data available")
            return None
        
        # Count nodes per SF
        sf_counts = defaultdict(int)
        for entry in sf_results:
            sf_counts[entry["sf"]] += 1
        
        # Plot distribution
        plt.figure(figsize=(10, 8))
        
        # Main SF distribution bar chart
        plt.subplot(2, 1, 1)
        sf_values = sorted(sf_counts.keys())
        counts = [sf_counts[sf] for sf in sf_values]
        
        bars = plt.bar(sf_values, counts)
        
        plt.xlabel('Spreading Factor (SF)')
        plt.ylabel('Number of Nodes')
        plt.title('Distribution of Spreading Factors')
        plt.grid(axis='y', linestyle='--', alpha=0.7)
        plt.xticks(sf_values)
        
        # Add value labels
        for bar in bars:
            height = bar.get_height()
            plt.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                    f'{int(height)}', ha='center', va='bottom')
        
        # Pie chart showing percentage distribution
        plt.subplot(2, 1, 2)
        plt.pie([sf_counts[sf] for sf in sf_values], 
                labels=[f'SF{sf}' for sf in sf_values],
                autopct='%1.1f%%',
                explode=[0.05] * len(sf_values),
                shadow=True)
        plt.axis('equal')
        plt.title('SF Distribution Percentage')
        
        plt.tight_layout()
        plt.show()
        return plt.gcf()
    
    def _export_plot(self, filename):
        os.makedirs(self.EXPORT_DIR, exist_ok=True)
        filepath = os.path.join(self.EXPORT_DIR, filename)
        plt.savefig(filepath, format='jpeg')
        print(f"Saved plot: {filepath}")

    def plot_pdr(self):
        pdr_data = self.calculate_pdr()
        node_ids = [entry['node_id'] for entry in pdr_data]
        pdr_values = [entry['pdr'] for entry in pdr_data]

        plt.figure(figsize=(12, 6))
        plt.bar(node_ids, pdr_values, color='skyblue')
        plt.xlabel('Node ID')
        plt.ylabel('Packet Delivery Ratio')
        plt.title('PDR per Node')
        plt.grid(True)
        plt.tight_layout()
        self._export_plot("pdr_per_node.jpeg")
        plt.close()
        
    def extract_last_sf_per_node(self):
        sf_map = {}
        for scalar in self.scalar_dict.get("finalSF", []):
            if scalar["entity_type"] == "node":
                sf_map[scalar["entity_id"]] = scalar["value"]
        print("SF values:", sf_map)
        return sf_map

    def extract_last_tp_per_node(self):
        tp_map = {}
        for scalar in self.scalar_dict.get("finalTP", []):
            if scalar["entity_type"] == "node":
                tp_map[scalar["entity_id"]] = scalar["value"]
        print("TP values:", tp_map)
        return tp_map

    def plot_pdr_vs_sf(self):
        pdr_data = self.calculate_pdr()
        sf_data = self.extract_last_sf_per_node()
        grouped = defaultdict(list)
        for entry in pdr_data:
            sf = sf_data.get(entry["node_id"])
            if sf is not None:
                grouped[sf].append(entry["pdr"])
        avg = {sf: sum(vals)/len(vals) for sf, vals in grouped.items()}
        keys = sorted(avg)
        plt.figure(figsize=(12, 6))
        plt.plot(keys, [avg[k] for k in keys], marker='o')
        plt.xlabel("SF")
        plt.ylabel("PDR")
        plt.title("PDR vs SF")
        plt.grid(True)
        self._export_plot("pdr_vs_sf.jpeg")
        plt.close()

    def plot_pdr_vs_tp(self):
        pdr_data = self.calculate_pdr()
        tp_data = self.extract_last_tp_per_node()
        grouped = defaultdict(list)
        for entry in pdr_data:
            tp = tp_data.get(entry["node_id"])
            if tp is not None:
                grouped[tp].append(entry["pdr"])
        avg = {tp: sum(vals)/len(vals) for tp, vals in grouped.items()}
        keys = sorted(avg)
        plt.figure(figsize=(12, 6))
        plt.plot(keys, [avg[k] for k in keys], marker='o', color='deepskyblue')
        plt.xlabel("TP (dBm)")
        plt.ylabel("PDR")
        plt.title("PDR vs TP")
        plt.grid(True)

        # Adaugă text dacă există doar un punct sau mai multe
        for tp in keys:
            val = avg[tp]
            count = len(grouped[tp])
            plt.text(tp, val + 0.005, f'{val:.3f}\nn={count}', ha='center', va='bottom')

        self._export_plot("pdr_vs_tp.jpeg")
        plt.close()

    def plot_energy_vs_tp(self):
        energy_data = self.calculate_energy_per_packet()
        tp_data = self.extract_last_tp_per_node()
        grouped = defaultdict(list)
        for entry in energy_data:
            tp = tp_data.get(entry["node_id"])
            if tp is not None:
                grouped[tp].append(entry["energy_per_packet_mJ"])
        avg = {tp: sum(vals)/len(vals) for tp, vals in grouped.items()}
        keys = sorted(avg)
        plt.figure(figsize=(12, 6))
        plt.plot(keys, [avg[k] for k in keys], marker='o', color='green')
        plt.xlabel("TP (dBm)")
        plt.ylabel("Energy (mJ)")
        plt.title("Energy vs TP")
        plt.grid(True)

        for tp in keys:
            val = avg[tp]
            count = len(grouped[tp])
            plt.text(tp, val + 0.001, f'{val:.3f}\nn={count}', ha='center', va='bottom')

        self._export_plot("energy_vs_tp.jpeg")
        plt.close()

    def plot_toa_vs_sf(self):
        toa_data = self.calculate_toa_per_node()
        sf_data = self.extract_last_sf_per_node()
        grouped = defaultdict(list)
        for entry in toa_data:
            sf = sf_data.get(entry["node_id"])
            if sf is not None:
                grouped[sf].append(entry["ToA_sec"] * 1000)
        avg = {sf: sum(vals)/len(vals) for sf, vals in grouped.items()}
        keys = sorted(avg)
        plt.figure(figsize=(12, 6))
        plt.plot(keys, [avg[k] for k in keys], marker='o', color='purple')
        plt.xlabel("SF")
        plt.ylabel("ToA (ms)")
        plt.title("ToA vs SF")
        plt.grid(True)
        self._export_plot("toa_vs_sf.jpeg")
        plt.close()

    def plot_toa_vs_tp(self):
        toa_data = self.calculate_toa_per_node()
        tp_data = self.extract_last_tp_per_node()
        grouped = defaultdict(list)
        for entry in toa_data:
            tp = tp_data.get(entry["node_id"])
            if tp is not None:
                grouped[tp].append(entry["ToA_sec"] * 1000)
        avg = {tp: sum(vals)/len(vals) for tp, vals in grouped.items()}
        keys = sorted(avg)
        plt.figure(figsize=(12, 6))
        plt.plot(keys, [avg[k] for k in keys], marker='o', color='purple')
        plt.xlabel("TP (dBm)")
        plt.ylabel("ToA (ms)")
        plt.title("ToA vs TP")
        plt.grid(True)

        for tp in keys:
            val = avg[tp]
            count = len(grouped[tp])
            plt.text(tp, val + 1, f'{val:.1f} ms\nn={count}', ha='center', va='bottom')

        self._export_plot("toa_vs_tp.jpeg")
        plt.close()
    
    def plot_energy_vs_nodes(self):
        energy_data = self.calculate_energy_per_packet()
        node_ids = [entry['node_id'] for entry in energy_data]
        energy_values = [entry['energy_per_packet_mJ'] for entry in energy_data]

        plt.figure(figsize=(12, 6))
        plt.bar(node_ids, energy_values, color='orange')
        plt.xlabel('Node ID')
        plt.ylabel('Energy per Received Packet (J)')
        plt.title('Energy Consumption per Node')
        plt.grid(True)
        plt.tight_layout()
        self._export_plot("energy_vs_node.jpeg")
        plt.close()

    def plot_energy_per_byte_vs_sf(self):
        energy_data = self.calculate_energy_per_packet()
        sf_data = self.extract_last_sf_per_node()

        grouped = defaultdict(list)
        for entry in energy_data:
            sf = sf_data.get(entry["node_id"])
            if sf is not None and entry['received'] > 0:
                bytes_received = entry['received'] * self.payload_size
                grouped[sf].append(entry['energy_consumed_mJ'] / bytes_received)

        avg = {sf: sum(vals) / len(vals) for sf, vals in grouped.items()}
        keys = sorted(avg)

        plt.figure(figsize=(12, 6))
        plt.plot(keys, [avg[k] for k in keys], marker='o', color='darkred')
        plt.xlabel("Spreading Factor (SF)")
        plt.ylabel("Energy per Byte (mJ)")
        plt.title("Energy per Byte vs SF")
        plt.grid(True)
        self._export_plot("energy_per_byte_vs_sf.jpeg")
        plt.close()

    def plot_throughput_vs_sf(self):
        sf_data = self.extract_last_sf_per_node()
        pdr_data = self.calculate_pdr()

        grouped = defaultdict(list)
        for entry in pdr_data:
            sf = sf_data.get(entry["node_id"])
            if sf is not None:
                throughput = entry['received'] * self.payload_size / self.sim_time
                grouped[sf].append(throughput)

        avg = {sf: sum(vals) / len(vals) for sf, vals in grouped.items()}
        keys = sorted(avg)

        plt.figure(figsize=(12, 6))
        plt.plot(keys, [avg[k] for k in keys], marker='o', color='teal')
        plt.xlabel("Spreading Factor (SF)")
        plt.ylabel("Throughput (bytes/sec)")
        plt.title("Throughput vs SF")
        plt.grid(True)
        self._export_plot("throughput_vs_sf.jpeg")
        plt.close()

    def plot_fer_vs_sf(self):
        per_data = self.calculate_per()
        sf_data = self.extract_last_sf_per_node()

        grouped = defaultdict(list)
        for entry in per_data:
            sf = sf_data.get(entry["node_id"])
            if sf is not None:
                grouped[sf].append(entry['per'])

        avg = {sf: sum(vals) / len(vals) for sf, vals in grouped.items()}
        keys = sorted(avg)

        plt.figure(figsize=(12, 6))
        plt.plot(keys, [avg[k] for k in keys], marker='o', color='darkorange')
        plt.xlabel("Spreading Factor (SF)")
        plt.ylabel("Frame Erasure Rate (FER)")
        plt.title("FER vs SF")
        plt.grid(True)
        self._export_plot("fer_vs_sf.jpeg")
        plt.close()

    def plot_duty_cycle_vs_sf(self):
        toa_data = self.calculate_toa_per_node()
        sf_data = self.extract_last_sf_per_node()

        grouped = defaultdict(list)
        for entry in toa_data:
            sf = sf_data.get(entry["node_id"])
            if sf is not None:
                packets_sent = next((s['value'] for s in self.scalar_dict.get("sentPackets", []) if s['entity_id'] == entry['node_id']), 0)
                total_airtime = entry['ToA_sec'] * packets_sent
                grouped[sf].append(100 * total_airtime / self.sim_time)

        avg = {sf: sum(vals) / len(vals) for sf, vals in grouped.items()}
        keys = sorted(avg)

        plt.figure(figsize=(12, 6))
        plt.plot(keys, [avg[k] for k in keys], marker='o', color='blue')
        plt.xlabel("Spreading Factor (SF)")
        plt.ylabel("Duty Cycle (%)")
        plt.title("Duty Cycle per SF")
        plt.grid(True)
        self._export_plot("duty_cycle_vs_sf.jpeg")
        plt.close()

    def plot_energy_efficiency_vs_tp(self):
        energy_data = self.calculate_energy_per_packet()
        tp_data = self.extract_last_tp_per_node()

        grouped = defaultdict(list)
        for entry in energy_data:
            tp = tp_data.get(entry["node_id"])
            if tp is not None:
                grouped[tp].append(entry['energy_per_packet_mJ'])

        avg = {tp: sum(vals) / len(vals) for tp, vals in grouped.items()}
        keys = sorted(avg)

        plt.figure(figsize=(12, 6))
        plt.plot(keys, [avg[k] for k in keys], marker='o', color='magenta')
        plt.xlabel("Transmission Power (dBm)")
        plt.ylabel("Energy per Packet (mJ)")
        plt.title("Energy Efficiency vs TP")
        plt.grid(True)
        self._export_plot("energy_efficiency_vs_tp.jpeg")
        plt.close()

    def plot_data_extraction_rate_cdf(self):
        """
        Plot the CDF of Data Extraction Rate (DER) across all nodes for the current scenario.
        """
        der_map = {
            node_id: 1.0 - der
            for node_id, der in self.metrics_summary.data_error_rate_map.items()
        }

        if not der_map:
            print(f"⚠️ No DER data for CDF in scenario: {self.metrics_summary.name}")
            return

        values = sorted(der_map.values())
        cdf = np.arange(1, len(values) + 1) / len(values)

        plt.figure(figsize=(10, 6))
        plt.plot(values, cdf, marker='o', linestyle='-', color='darkgreen')
        plt.xlabel("Data Extraction Rate (DER)")
        plt.ylabel("Cumulative Probability")
        plt.title(f"DER Cumulative Distribution Function (CDF) - {self.metrics_summary.name}")
        plt.grid(True, linestyle='--', alpha=0.6)
        plt.tight_layout()

        self._export_plot("der_cdf.jpeg")
        plt.close()
    
    def plot_data_extraction_rate_vs_signal_quality(self):
        """
        Plot DER vs Signal Quality (SNIR and RSSI) using average scalar per node.
        This method runs per scenario and is meant to be called from plot_all().
        """
        der_map = {
            node_id: 1.0 - der
            for node_id, der in self.metrics_summary.data_error_rate_map.items()
        }

        # Fallback: compute signal maps by vector order if not already set
        if not self.metrics_summary.snir_map and self.metrics_summary.snir_vectors:
            self.metrics_summary.snir_map = compute_average_signal_map_by_order(self.metrics_summary.snir_vectors)

        if not self.metrics_summary.rssi_map and self.metrics_summary.rssi_vectors:
            self.metrics_summary.rssi_map = compute_average_signal_map_by_order(self.metrics_summary.rssi_vectors)

        for signal_type, signal_map, label, vecs in [
            ("snir", self.metrics_summary.snir_map, "SNIR (dB)", self.metrics_summary.snir_vectors),
            ("rssi", self.metrics_summary.rssi_map, "RSSI (dBm)", self.metrics_summary.rssi_vectors),
        ]:
            if not signal_map and not vecs:
                print(f"⚠️ No {signal_type.upper()} data found for {self.metrics_summary.name}")
                continue

            x_vals = []
            y_vals = []
            for node_id in der_map:
                if node_id in signal_map:
                    x_vals.append(signal_map[node_id])
                    y_vals.append(der_map[node_id])

            if not x_vals:
                print(f"⚠️ No valid data for {signal_type.upper()} vs DER in {self.metrics_summary.name}")
                continue

            # Assign color per node_id (just reuse DER node keys)
            node_ids = list(der_map.keys())
            colors = [plt.cm.tab10(node_id % 10) for node_id in node_ids[:len(x_vals)]]

            plt.figure(figsize=(10, 6))
            plt.scatter(x_vals, y_vals, c=colors, edgecolor='black', alpha=0.7, label="Nodes")

            # 🔷 Add stable smooth spline fit
            if len(x_vals) >= 4:
                try:
                    sorted_indices = np.argsort(x_vals)
                    x_sorted = np.array(x_vals)[sorted_indices]
                    y_sorted = np.array(y_vals)[sorted_indices]

                    # Optional: Jitter x to break near-ties
                    x_sorted += np.random.uniform(-0.001, 0.001, size=len(x_sorted))

                    # Linear spline to avoid overfitting
                    spline = make_interp_spline(x_sorted, y_sorted, k=1)
                    x_smooth = np.linspace(min(x_sorted), max(x_sorted), 200)
                    y_smooth = spline(x_smooth)
                    y_smooth = np.clip(y_smooth, 0, 1)  # Clamp DER

                    plt.plot(x_smooth, y_smooth, linestyle="--", color="gray", label="Smooth Fit")
                except Exception as e:
                    print(f"⚠️ Could not generate smooth fit for {signal_type.upper()} due to: {e}")

            plt.xlabel(label)
            plt.ylabel("Data Extraction Rate (DER)")
            plt.title(f"Data Extraction Rate vs {signal_type.upper()} - {self.metrics_summary.name}")
            plt.grid(True, linestyle='--', alpha=0.6)
            plt.legend()
            plt.tight_layout()

            self._export_plot(f"der_vs_{signal_type}.jpeg")
            plt.close()
            
    def plot_collision_count_per_gateway(self):
        """Plot number of collisions per gateway from scalar data"""
        plt.figure(figsize=(12, 6))
        
        scalar_list = self.scalar_dict.get("numCollisions", [])
        collision_counts = {
            entry["entity_id"]: entry["value"]
            for entry in scalar_list if entry["entity_type"] == "gateway" and entry["entity_id"] is not None
        }

        if not collision_counts:
            print("⚠️ No collision scalar data found for gateways.")
            return

        ids = sorted(collision_counts.keys())
        values = [collision_counts[i] for i in ids]

        plt.bar(ids, values, color='salmon', edgecolor='black')
        plt.xlabel("Gateway ID")
        plt.ylabel("Collision Count")
        plt.title("Collision Count per Gateway")
        plt.grid(True, axis='y')
        plt.tight_layout()
        self._export_plot("collision_count_per_gateway.jpeg")
        plt.close()

    def plot_collision_count_per_node(self):
        """Plot number of collisions per node from scalar data"""
        plt.figure(figsize=(12, 6))
        
        scalar_list = self.scalar_dict.get("numCollisions", [])
        collision_counts = {
            entry["entity_id"]: entry["value"]
            for entry in scalar_list if entry["entity_type"] == "node" and entry["entity_id"] is not None
        }

        if not collision_counts:
            print("⚠️ No collision scalar data found for nodes.")
            return

        ids = sorted(collision_counts.keys())
        values = [collision_counts[i] for i in ids]

        plt.bar(ids, values, color='lightblue', edgecolor='black')
        plt.xlabel("Node ID")
        plt.ylabel("Collision Count")
        plt.title("Collision Count per Node")
        plt.grid(True, axis='y')
        plt.tight_layout()
        self._export_plot("collision_count_per_node.jpeg")
        plt.close()

    def plot_convergence_time_per_node(self):
        sf_vectors = {v['module']: v['value'] for v in self.sf_vectors if 'value' in v}
        times = []
        for module, values in sf_vectors.items():
            if not values:
                continue
            node_id = self._extract_node_or_gateway_number(module, self.NODE_PREFIX)
            if node_id is not None:
                convergence_time = len(values)  # placeholder: count of changes
                times.append((node_id, convergence_time))

        times.sort()
        node_ids, conv_times = zip(*times)

        plt.figure(figsize=(12, 6))
        plt.bar(node_ids, conv_times, color='slateblue')
        plt.xlabel("Node ID")
        plt.ylabel("SF Update Events")
        plt.title("Convergence Activity (SF Changes per Node)")
        plt.grid(True)
        self._export_plot("convergence_activity_sf.jpeg")
        plt.close()

    def plot_rssi_distribution(self, style='histogram'):
        """
        Plot RSSI distribution per node using OMNeT++-style binning.

        Args:
            style (str): 'histogram' or 'line'
        """

        plt.figure(figsize=(12, 6))
        plotted = False

        for vec in self.rssi_vectors:
            values = vec.get("value", [])
            if not values:
                continue

            node_id = self._extract_node_or_gateway_number(vec['module'], self.NODE_PREFIX)
            label = vec['module'] if node_id is None else f"Node {node_id}"

            # OMNeT++-style binning
            bin_edges = omnet_histogram_bin_edges(values)
            bin_counts, _ = np.histogram(values, bins=bin_edges)
            bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2

            if style == 'line':
                plt.plot(bin_centers, bin_counts, label=label)
            elif style == 'histogram':
                plt.bar(bin_centers, bin_counts, width=np.diff(bin_edges), alpha=0.6, edgecolor='black', label=label)
            else:
                raise ValueError("Invalid style. Use 'histogram' or 'line'.")

            plotted = True

        if not plotted:
            print("⚠️ No RSSI data found.")
            return

        plt.xlabel("RSSI (dBm)")
        plt.ylabel("Count")
        plt.title(f"RSSI Distribution per Node ({style.capitalize()})")
        plt.legend()
        plt.grid(True)
        plt.tight_layout()
        self._export_plot(f"rssi_distribution_{style}_omnet_style.jpeg")
        plt.close()

    def plot_snir_distribution(self, style='histogram'):
        """
        Plot SNIR distribution per node using OMNeT++-style binning.

        Args:
            style (str): 'histogram' or 'line'
        """
        plt.figure(figsize=(12, 6))
        plotted = False

        for vec in self.snir_vectors:
            values = vec.get("value", [])
            if not values:
                continue

            node_id = self._extract_node_or_gateway_number(vec['module'], self.NODE_PREFIX)
            label = vec['module'] if node_id is None else f"Node {node_id}"

            bin_edges = omnet_histogram_bin_edges(values)
            bin_counts, _ = np.histogram(values, bins=bin_edges)
            bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2

            if style == 'line':
                plt.plot(bin_centers, bin_counts, label=label)
            elif style == 'histogram':
                plt.bar(bin_centers, bin_counts, width=np.diff(bin_edges), alpha=0.6, edgecolor='black', label=label)
            else:
                raise ValueError("Invalid style. Use 'histogram' or 'line'.")

            plotted = True

        if not plotted:
            print("⚠️ No SNIR data found.")
            return

        plt.xlabel("SNIR (dB)")
        plt.ylabel("Count")
        plt.title(f"SNIR Distribution per Node ({style.capitalize()})")
        plt.legend()
        plt.grid(True)
        plt.tight_layout()
        self._export_plot(f"snir_distribution_{style}_omnet_style.jpeg")
        plt.close()

    def plot_rssi_vs_time(self):
        """Plot RSSI over time for each node"""
        plt.figure(figsize=(12, 6))
        plotted = False

        for vec in self.rssi_vectors:
            times = vec.get("time", [])
            values = vec.get("value", [])
            if not times or not values:
                continue
            node_id = self._extract_node_or_gateway_number(vec['module'], self.NODE_PREFIX)
            label = f"Node {node_id}" if node_id is not None else vec['module']
            plt.plot(times, values, label=label)
            plotted = True

        if not plotted:
            print("⚠️ No RSSI time-series data found.")
            return

        plt.xlabel("Simulation Time [s]")
        plt.ylabel("RSSI (dBm)")
        plt.title("RSSI over Time per Node")
        plt.legend()
        plt.grid(True)
        plt.tight_layout()
        self._export_plot("rssi_time_plot.jpeg")
        plt.close()

    def plot_snir_vs_time(self):
        """Plot SNIR over time for each node"""
        plt.figure(figsize=(12, 6))
        plotted = False

        for vec in self.snir_vectors:
            times = vec.get("time", [])
            values = vec.get("value", [])
            if not times or not values:
                continue
            node_id = self._extract_node_or_gateway_number(vec['module'], self.NODE_PREFIX)
            label = f"Node {node_id}" if node_id is not None else vec['module']
            plt.plot(times, values, label=label)
            plotted = True

        if not plotted:
            print("⚠️ No SNIR time-series data found.")
            return

        plt.xlabel("Simulation Time [s]")
        plt.ylabel("SNIR (dB)")
        plt.title("SNIR over Time per Node")
        plt.legend()
        plt.grid(True)
        plt.tight_layout()
        self._export_plot("snir_time_plot.jpeg")
        plt.close()

    def plot_final_sf_tp_per_node(self):
        """Plot final SF and TP values per node if available as scalars"""
        final_sf = {}
        final_tp = {}

        for scalar in self.scalars:
            mod = scalar.get("module", "")
            if "loRaNodes[" in mod:
                node_id = self._extract_node_or_gateway_number(mod, "loRaNodes[")
                if node_id is None:
                    continue
                if scalar.get("name") == "finalSF":
                    final_sf[node_id] = scalar["value"]
                elif scalar.get("name") == "finalTP":
                    final_tp[node_id] = scalar["value"]

        if final_sf:
            ids = sorted(final_sf.keys())
            values = [final_sf[i] for i in ids]
            plt.figure(figsize=(12, 6))
            plt.bar(ids, values, color='orchid', edgecolor='black')
            plt.xlabel("Node ID")
            plt.ylabel("Final SF")
            plt.title("Final Spreading Factor per Node")
            plt.grid(True, axis='y')
            plt.tight_layout()
            self._export_plot("final_sf_per_node.jpeg")
            plt.close()

        if final_tp:
            ids = sorted(final_tp.keys())
            values = [final_tp[i] for i in ids]
            plt.figure(figsize=(12, 6))
            plt.bar(ids, values, color='orange', edgecolor='black')
            plt.xlabel("Node ID")
            plt.ylabel("Final TP (dBm)")
            plt.title("Final Transmission Power per Node")
            plt.grid(True, axis='y')
            plt.tight_layout()
            self._export_plot("final_tp_per_node.jpeg")
            plt.close()

    def plot_packets_sent_per_node(self):
        """Plot number of packets sent per node based on scalar 'LoRa_AppPacketSent:count'"""
        pkt_counts = {}
        for scalar in self.scalars:
            if scalar.get("name") == "LoRa_AppPacketSent:count" and "loRaNodes[" in scalar.get("module", ""):
                node_id = self._extract_node_or_gateway_number(scalar["module"], "loRaNodes[")
                if node_id is not None:
                    pkt_counts[node_id] = scalar["value"]

        if not pkt_counts:
            print("⚠️ No sent packet data per node found.")
            return

        ids = sorted(pkt_counts.keys())
        values = [pkt_counts[i] for i in ids]

        plt.figure(figsize=(12, 6))
        plt.bar(ids, values, color='limegreen', edgecolor='black')
        plt.xlabel("Node ID")
        plt.ylabel("Packets Sent")
        plt.title("Packets Sent per Node")
        plt.grid(True, axis='y')
        plt.tight_layout()
        self._export_plot("packets_sent_per_node.jpeg")
        plt.close()

    def plot_snr_margin_distribution(self):
        plt.figure(figsize=(12, 6))
        plotted = False

        for vec in self.snr_margin_vectors:
            values = vec.get("value", [])
            if not values:
                continue

            label = vec.get("module", "unknown")

            # OMNeT++-like binning: integer bin steps
            min_val = int(min(values)) - 1
            max_val = int(max(values)) + 1
            bin_edges = np.arange(min_val, max_val + 1, 1)

            bin_counts, _ = np.histogram(values, bins=bin_edges)
            bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2

            plt.bar(bin_centers, bin_counts, width=1, alpha=0.6, label=label)
            plotted = True

        if not plotted:
            print("⚠️ No SNR Margin data found.")
            return

        plt.xlabel("SNR Margin (dB)")
        plt.ylabel("Count")
        plt.title("SNR Margin Distribution per Node (OMNeT++ Style)")
        plt.legend()
        plt.grid(True)
        plt.tight_layout()
        self._export_plot("snr_margin_distribution_histogram_omnet_style.jpeg")
        plt.close()

    def plot_data_extraction_rate_per_sf(self):
        """Plot DER values per SF (from scalars: DER SF7 to SF12)"""
        sf_labels = [f"SF{i}" for i in range(7, 13)]
        der_vals = []

        for sf in sf_labels:
            for scalar in self.scalars:
                if scalar.get("name") == f"DER {sf}":
                    der_vals.append(scalar["value"])
                    break
            else:
                der_vals.append(0.0)

        plt.figure(figsize=(12, 6))
        plt.bar(sf_labels, der_vals, color='royalblue', edgecolor='black')
        plt.xlabel("Spreading Factor")
        plt.ylabel("DER")
        plt.title("DER per Spreading Factor")
        plt.grid(True, axis='y')
        plt.tight_layout()
        self._export_plot("data_extraction_rate_per_sf.jpeg")
        plt.close()

    def plot_energy_per_delivered_packet(self):
        """Plot energy consumed per delivered packet per node"""
        energy = {}
        delivered = {}

        for scalar in self.scalars:
            mod = scalar.get("module", "")
            if "loRaNodes[" in mod:
                node_id = self._extract_node_or_gateway_number(mod, "loRaNodes[")
                if node_id is None:
                    continue
                if scalar["name"] == "totalEnergyConsumed":
                    energy[node_id] = scalar["value"]
                elif scalar["name"] == "numReceived":
                    delivered[node_id] = scalar["value"]

        values = []
        ids = []
        for i in sorted(set(energy) & set(delivered)):
            if delivered[i] > 0:
                values.append(energy[i] / delivered[i])
            else:
                values.append(0)
            ids.append(i)

        if not values:
            print("⚠️ No energy or delivery data found.")
            return

        plt.figure(figsize=(12, 6))
        plt.bar(ids, values, color='darkred', edgecolor='black')
        plt.xlabel("Node ID")
        plt.ylabel("Energy / Delivered Packet")
        plt.title("Energy Consumption per Delivered Packet")
        plt.grid(True, axis='y')
        plt.tight_layout()
        self._export_plot("energy_per_delivered_packet.jpeg")
        plt.close()

    def plot_packet_loss_breakdown(self):
        """Plot stacked bar chart of packet loss causes per node"""
        loss_causes = {
            "RetryLimit": "packetDropRetryLimitReached:count",
            "Sensitivity": "rcvBelowSensitivity",
            "Incorrect": "packetDropIncorrectlyReceived:count",
            "NotAddressed": "packetDropNotAddressedToUs:count",
            "QueueOverflow": "packetDropQueueOverflow:count"
        }

        node_loss = defaultdict(lambda: {k: 0 for k in loss_causes})

        for scalar in self.scalars:
            mod = scalar.get("module", "")
            if "loRaNodes[" not in mod:
                continue
            node_id = self._extract_node_or_gateway_number(mod, "loRaNodes[")
            for k, loss_name in loss_causes.items():
                if scalar.get("name") == loss_name:
                    node_loss[node_id][k] = scalar["value"]

        if not node_loss:
            print("⚠️ No packet loss data found.")
            return

        labels = sorted(node_loss.keys())
        bottoms = np.zeros(len(labels))
        x = np.arange(len(labels))
        plt.figure(figsize=(12, 6))

        for k in loss_causes:
            heights = [node_loss[i][k] for i in labels]
            plt.bar(x, heights, bottom=bottoms, label=k)
            bottoms += heights

        plt.xticks(x, labels)
        plt.xlabel("Node ID")
        plt.ylabel("Packets Dropped")
        plt.title("Packet Loss Breakdown per Cause")
        plt.legend()
        plt.tight_layout()
        self._export_plot("packet_loss_breakdown.jpeg")
        plt.close()

    def plot_cdf_distribution(self, vectors, title, xlabel, filename):
        """Generic function to plot CDF from a list of vectors"""
        all_values = []
        for vec in vectors:
            all_values.extend(vec.get("value", []))

        if not all_values:
            print(f"⚠️ No data for {title} CDF.")
            return

        sorted_vals = np.sort(all_values)
        cdf = np.arange(len(sorted_vals)) / len(sorted_vals)

        plt.figure(figsize=(12, 6))
        plt.plot(sorted_vals, cdf)
        plt.xlabel(xlabel)
        plt.ylabel("CDF")
        plt.title(title)
        plt.grid(True)
        plt.tight_layout()
        self._export_plot(filename)
        plt.close()

    def plot_adr_device_margin_per_node(self):
        """
        Plot adrDeviceMargin value (from parameters) for each end device node.
        This assumes the same value is applied to all nodes unless specified otherwise.
        """
        margin_str = self.parameters.get("adrDeviceMargin")
        if margin_str is None:
            print("⚠️ 'adrDeviceMargin' not found in parameters.")
            return

        try:
            adr_margin = float(margin_str)
        except ValueError:
            print(f"⚠️ Could not convert adrDeviceMargin '{margin_str}' to float.")
            return

        # ✅ Extract node IDs from ScenarioMetrics (where pdr_map lives)
        metrics = getattr(self, "metrics_summary", None)
        if metrics and metrics.pdr_map:
            node_ids = sorted(metrics.pdr_map.keys())
        else:
            node_ids = list(range(10))  # fallback

        y_vals = [adr_margin] * len(node_ids)

        plt.figure(figsize=(10, 5))
        bars = plt.bar(node_ids, y_vals, color='lightgreen', edgecolor='black')
        for bar, val in zip(bars, y_vals):
            plt.text(bar.get_x() + bar.get_width() / 2, val, f"{val:.1f}", ha='center', va='bottom', fontsize=9)

        plt.xlabel("Node ID")
        plt.ylabel("ADR Device Margin (dB)")
        plt.title("ADR Device Margin per Node (from Parameters)")
        plt.grid(True, linestyle='--', alpha=0.5)
        plt.tight_layout()
        self._export_plot("adr_device_margin_per_node.jpeg")
        plt.close()

    def get_data_extraction_rate_per_gateway(self):
        """
        Extract Data Extraction Rate (DER) values per Gateway from scalar_dict.
        DER is expected under module names like: LoRaNetworkTest.loRaGW[0].LoRaGWNic.radio
        """
        data_extraction_rate_per_gateway = {}

        for scalar_name, scalars in self.scalar_dict.items():
            if scalar_name.startswith('DER'):  # Match only DER metrics
                for scalar in scalars:
                    module = scalar.get("module", "")
                    if module.startswith(self.GW_PREFIX):
                        try:
                            # Extract gateway ID between square brackets: loRaGW[3] → 3
                            gw_part = module.split('[')[1].split(']')[0]
                            gw_id = int(gw_part)
                            data_extraction_rate_per_gateway[gw_id] = scalar["value"]
                        except Exception as e:
                            print(f"[WARN] Could not parse GW ID from '{module}': {e}")

        return data_extraction_rate_per_gateway

    def plot_data_extraction_rate_per_gateway(self):
        """
        Plot Data Extraction Rate per Gateway using scalar_dict and save the image
        as data_extraction_rate_per_gateway.jpeg in self.EXPORT_DIR.
        """
        der_map = self.get_data_extraction_rate_per_gateway()
        if not der_map:
            print(f"[WARN] No data extraction rate found for scenario '{getattr(self, 'scenario_name', 'Unknown')}'")
            return

        gateway_ids = sorted(der_map.keys())
        values = [der_map[gw_id] for gw_id in gateway_ids]

        plt.figure(figsize=(10, 5))
        bars = plt.bar([f"GW {gw}" for gw in gateway_ids], values, color='dodgerblue', edgecolor='black')

        # Annotate values on top of each bar
        for bar, val in zip(bars, values):
            plt.text(bar.get_x() + bar.get_width() / 2, val + 0.01, f"{val:.2f}",
                    ha='center', va='bottom', fontsize=9)

        plt.xlabel("Gateway ID")
        plt.ylabel("Data Extraction Rate")
        plt.title("Data Extraction Rate per Gateway")
        plt.grid(axis='y', linestyle='--', alpha=0.5)
        plt.tight_layout()

        os.makedirs(self.EXPORT_DIR, exist_ok=True)
        filepath = os.path.join(self.EXPORT_DIR, "data_extraction_rate_per_gateway.jpeg")
        plt.savefig(filepath)
        plt.close()

        print(f"✅ Saved: {filepath}")

    def plot_all(self):
        print("\n\n=== GENERATING VISUALIZATIONS ===\n")
        print("Plotting PDR vs Nodes...")
        self.plot_pdr()
        print("Plotting PDR vs SF...")
        self.plot_pdr_vs_sf()
        print("Plotting Spreading Factor Distribution...")
        self.plot_spreading_factor_distribution()
        print("Plotting PDR vs TP...")
        self.plot_pdr_vs_tp()
        print("Plotting Energy Consumption vs Nodes...")
        self.plot_energy_vs_nodes()
        print("Plotting Energy Consumption vs TP...")
        self.plot_energy_vs_tp()
        print("Plotting Time on Air vs SF...")
        self.plot_toa_vs_sf()
        print("Plotting Time on Air vs TP...")
        self.plot_toa_vs_tp()
        print("Plotting Energy per Byte vs SF...")
        self.plot_energy_per_byte_vs_sf()
        print("Plotting Throughput vs SF...")
        self.plot_throughput_vs_sf()
        print("Plotting FER vs SF...")
        self.plot_fer_vs_sf()
        print("Plotting Duty Cycle vs SF...")
        self.plot_duty_cycle_vs_sf()
        print("Plotting Energy Efficiency vs TP...")
        self.plot_energy_efficiency_vs_tp()
        print("Plotting Collision Count vs Gateway...")
        self.plot_collision_count_per_gateway()
        print("Plotting Collision Count vs Node...")
        self.plot_collision_count_per_node()
        print("Plotting Convergence Time per Node...")
        self.plot_convergence_time_per_node()
        print("Plotting RSSI vs Time...")
        self.plot_rssi_vs_time()
        print("Plotting SNIR vs Time...")
        self.plot_snir_vs_time()
        print("Plotting Final SF / TP per Node...")
        self.plot_final_sf_tp_per_node()
        print("Plotting Packets Sent per Node...")
        self.plot_packets_sent_per_node()
        print("Plotting DER per SF...")
        self.plot_data_extraction_rate_per_sf()
        print("Plotting Energy per Delivered Packet...")
        self.plot_energy_per_delivered_packet()
        print("Plotting Packet Loss Breakdown per Cause...")
        self.plot_packet_loss_breakdown()
        print("Plotting RSSI CDF...")
        self.plot_cdf_distribution(self.rssi_vectors, "RSSI CDF", "RSSI (dBm)", "cdf_rssi.jpeg")
        print("Plotting SNIR CDF...")
        self.plot_cdf_distribution(self.snir_vectors, "SNIR CDF", "SNIR (dB)", "cdf_snir.jpeg")
        print("Plotting SNR Margin...")
        self.plot_adr_device_margin_per_node()
        print("Plotting SNR Margin Line Distribution...")
        self.plot_snr_margin_distribution()  # or 'histogram'
        print("Plotting RSSI Histogram Distribution...")
        self.plot_rssi_distribution(style='histogram')  # or 'histogram'
        print("Plotting SNIR Histogram Distribution...")
        self.plot_snir_distribution(style='histogram')       # or 'histogram'
        print("Plotting RSSI Line Distribution...")
        self.plot_rssi_distribution(style='line')  # or 'line'
        print("Plotting SNIR Line Distribution...")
        self.plot_snir_distribution(style='line')       # or 'line'
        print("Plotting Data Error Rate per Node...")
        self.plot_data_extraction_rate_per_gateway()
        print(f"Plotting Data Error Rate per Node..")
        self.plot_data_error_rate_per_node()
        print("Plotting DER vs Signal Quality (SNIR/RSSI)...")
        self.plot_data_extraction_rate_vs_signal_quality()
        print("Plotting DER CDF...")
        self.plot_data_extraction_rate_cdf()

def compute_average_signal_map_by_order(vectors):
    avg_map = {}
    for node_id, vec in enumerate(vectors):
        values = vec.get("value", [])
        if values:
            avg_map[node_id] = float(np.mean(values))
    return avg_map


def omnet_histogram_bin_edges(values, bins=None, range=None, weights=None):
    values = np.asarray(values)
    if bins is not None and not isinstance(bins, int):
        if range is None:
            min_value = values.min()
            max_value = values.max()
            value_range = max_value - min_value
            range = (min_value, max_value + value_range * 0.01)
        return np.histogram_bin_edges(values, bins, range, weights)

    all_integers = np.all(np.equal(np.mod(values, 1), 0))
    min_value = values.min() if range is None else range[0]
    max_value = values.max() if range is None else range[1]
    value_range = max_value - min_value

    if value_range == 0:
        edges = np.array([min_value, min_value + 1])
    elif all_integers:
        bin_size = max(1, round(value_range / (bins or 10)))
        edges = np.arange(min_value, max_value + 1 + bin_size, bin_size)
    else:
        range = range or (min_value, max_value + value_range * 0.01)
        edges = np.histogram_bin_edges(values, bins or 'auto', range, weights)

    return edges

def plot_data_error_rate_per_node_across_scenarios(metrics_per_scenario, output_dir="plots"):
    os.makedirs(output_dir, exist_ok=True)

    scenario_names = list(metrics_per_scenario.keys())
    node_ids = sorted({node_id for metrics in metrics_per_scenario.values()
                       for node_id in metrics.data_error_rate_map.keys()})

    x = np.arange(len(node_ids))  # Node ID positions on x-axis
    width = 0.8 / len(scenario_names)  # Width of each bar group

    plt.figure(figsize=(14, 6))
    for i, scenario in enumerate(scenario_names):
        metrics = metrics_per_scenario[scenario]
        y = [metrics.data_error_rate_map.get(nid, 0) for nid in node_ids]
        bars = plt.bar(x + i * width, y, width=width, label=scenario)

        # Annotate bars
        for bar in bars:
            height = bar.get_height()
            if height > 0:
                plt.text(bar.get_x() + bar.get_width()/2, height + 0.01,
                         f"{height:.2f}", ha='center', va='bottom', fontsize=8)

    plt.xticks(x + width * (len(scenario_names) - 1) / 2, [f"Node {i}" for i in node_ids])
    plt.xlabel("Node ID")
    plt.ylabel("Data Error Rate")
    plt.title("Data Error Rate per Node Across Scenarios")
    plt.legend()
    plt.grid(axis='y', linestyle='--', alpha=0.5)
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "data_error_rate_per_node_across_scenarios.jpeg"))
    plt.close()

    print(f"✅ Saved: data_error_rate_per_node_across_scenarios.jpeg")

def plot_data_extraction_rate_per_gateway(metrics_per_scenario, output_dir="plots"):
    os.makedirs(output_dir, exist_ok=True)

    all_gateway_ids = sorted(set(
        gw_id for metrics in metrics_per_scenario.values()
        for gw_id in metrics.data_extraction_rate_per_gateway.keys()
    ))

    scenarios = list(metrics_per_scenario.keys())
    bar_width = 0.8 / len(scenarios)
    x = np.arange(len(all_gateway_ids))

    plt.figure(figsize=(14, 6))
    for i, scenario in enumerate(scenarios):
        metrics = metrics_per_scenario[scenario]
        values = [metrics.data_extraction_rate_per_gateway.get(gw_id, 0) for gw_id in all_gateway_ids]
        plt.bar(x + i * bar_width, values, width=bar_width, label=scenario)

    plt.xticks(x + bar_width * (len(scenarios) - 1) / 2, [f"GW {gw}" for gw in all_gateway_ids])
    plt.ylabel("Data Extraction Rate")
    plt.title("Data Extraction Rate per Gateway Across Scenarios")
    plt.legend()
    plt.grid(axis='y', linestyle='--', alpha=0.5)
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "data_extraction_rate_per_gateway_across_scenarios.jpeg"))
    plt.close()

def plot_spreading_factor_per_node_across_scenarios(metrics_per_scenario, output_dir="plots"):
    """
    Plot a histogram of Spreading Factor (SF) usage across all scenarios using sf_vectors.
    Adds percentage labels on bars and total occurrences in legend.
    """
    os.makedirs(output_dir, exist_ok=True)

    sf_range = range(7, 13)  # SF7 to SF12
    bins = np.arange(6.5, 13.5, 1)  # Bin edges for histogram

    plt.figure(figsize=(12, 6))

    bar_width = 0.12
    offset = 0
    colors = plt.cm.get_cmap("tab10")

    for idx, (scenario, metrics) in enumerate(metrics_per_scenario.items()):
        if not hasattr(metrics, "analyzer_ref") or not metrics.analyzer_ref:
            continue

        analyzer = metrics.analyzer_ref
        sf_data = []
        for vec in analyzer.sf_vectors:
            sf_data.extend(vec.get("value", []))

        if not sf_data:
            continue

        total = len(sf_data)
        counts, _ = np.histogram(sf_data, bins=bins)

        x_pos = np.array(sf_range) + offset
        label_with_total = f"{scenario} (total: {total})"
        plt.bar(x_pos, counts, width=bar_width, alpha=0.8, edgecolor='black',
                label=label_with_total, color=colors(idx % 10))

        # Add % labels on top of each bar
        for i, count in enumerate(counts):
            if count > 0:
                percent = 100 * count / total
                plt.text(x_pos[i], count + 1, f"{percent:.1f}%", ha='center', fontsize=8)

        offset += bar_width

    plt.xlabel("Spreading Factor (SF)")
    plt.ylabel("Occurrences")
    plt.title("Spreading Factor per Node Across Scenarios")
    plt.xticks(np.arange(7, 13))
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    output_path = os.path.join(output_dir, "spreading_factor_per_node_across_scenarios.jpeg")
    plt.savefig(output_path)
    plt.close()

def plot_rssi_distribution_across_scenarios(metrics_per_scenario, output_dir="plots"):
    os.makedirs(output_dir, exist_ok=True)
    plt.figure(figsize=(12, 6))
    plotted = False

    for scenario, metrics in metrics_per_scenario.items():
        if not getattr(metrics, 'rssi_vectors', None):
            continue

        all_values = []
        for vec in metrics.rssi_vectors:
            values = vec.get("value", [])
            if values:
                all_values.extend(values)

        if not all_values:
            continue

        bin_edges = np.histogram_bin_edges(all_values, bins='auto')
        bin_counts, _ = np.histogram(all_values, bins=bin_edges)
        bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2

        plt.bar(bin_centers, bin_counts, width=np.diff(bin_edges), alpha=0.6, edgecolor='black',
                label=f"{scenario} ({sum(bin_counts)} samples)")
        plotted = True

    if not plotted:
        print("⚠️ No RSSI data available across any scenario.")
        return

    plt.xlabel("RSSI (dBm)")
    plt.ylabel("Count")
    plt.title("RSSI Distribution Across Scenarios")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "rssi_distribution_across_scenarios.jpeg"))
    plt.close()

def plot_der_per_node_vs_gateways(metrics_per_scenario, output_dir: str):
    der_data = {
        "1ed": defaultdict(dict),   # {gw: {node_id: der}}
        "10ed": defaultdict(dict)
    }

    # Extract DER values
    for scenario_name, metrics in metrics_per_scenario.items():
        match = re.search(r'(\d+)GW.*-(\d+)ed', scenario_name)
        if not match:
            continue

        num_gw = int(match.group(1))
        num_ed = int(match.group(2))
        key = "1ed" if num_ed == 1 else "10ed" if num_ed == 10 else None
        if key is None:
            continue

        for node_id, der in metrics.data_error_rate_map.items():
            der_data[key][num_gw][node_id] = der

    for key in ["1ed", "10ed"]:
        gateway_values = sorted(der_data[key].keys())
        node_ids = sorted(set().union(*[d.keys() for d in der_data[key].values()]))

        # === 📊 Bar Plot: DER per node per gateway
        fig1, ax1 = plt.subplots(figsize=(14, 6))
        width = 0.1
        bar_positions = np.arange(len(node_ids))
        num_groups = len(gateway_values)
        colors = plt.cm.tab10.colors

        for i, gw in enumerate(gateway_values):
            der_per_node = der_data[key][gw]
            heights = [der_per_node.get(nid, 0.0) for nid in node_ids]
            positions = bar_positions + (i - num_groups / 2) * width + width / 2

            bars = ax1.bar(positions, heights, width=width, color=colors[i % len(colors)], label=f"{gw} GW")

            for j, height in enumerate(heights):
                if height > 0:
                    ax1.text(
                        positions[j],
                        height + 0.01,
                        f"{height:.2f}",
                        ha='center',
                        va='bottom',
                        fontsize=7,
                        rotation=90
                    )

        ax1.set_xlabel("Node ID")
        ax1.set_ylabel("Data Error Rate (DER)")
        ax1.set_title(f"DER per Node (Grouped by Gateway Count) - {key}")
        ax1.set_xticks(bar_positions)
        ax1.set_xticklabels(node_ids)
        ax1.set_ylim(0, 1.05)
        ax1.grid(axis='y', linestyle='--', alpha=0.5)
        ax1.legend(title="Gateways", loc="upper right")
        fig1.tight_layout()

        filename_bar = f"der_per_node_vs_gateways_{key}_BARS.jpeg"
        path_bar = os.path.join(output_dir, filename_bar)
        plt.savefig(path_bar, format="jpeg")
        plt.close()
        print(f"✅ Saved bar plot: {path_bar}")

        # === 📈 Line Plot: DER evolution per node vs number of gateways
        fig2, ax2 = plt.subplots(figsize=(14, 6))
        for node_id in node_ids:
            x_vals = []
            y_vals = []
            for gw in gateway_values:
                der = der_data[key][gw].get(node_id, None)
                if der is not None:
                    x_vals.append(gw)
                    y_vals.append(der)

            if x_vals:
                ax2.plot(
                    x_vals,
                    y_vals,
                    linestyle='-',
                    marker='o',
                    linewidth=1.5,
                    alpha=0.8,
                    label=f"Node {node_id}"
                )

        ax2.set_xlabel("Number of Gateways")
        ax2.set_ylabel("Data Error Rate (DER)")
        ax2.set_title(f"DER Evolution per Node vs Gateways - {key}")
        ax2.set_xticks(gateway_values)
        ax2.set_ylim(0, 1.05)
        ax2.grid(True, linestyle='--', alpha=0.6)
        ax2.legend(title="Nodes", loc="upper right", fontsize=8, ncol=2)
        fig2.tight_layout()

        filename_line = f"der_per_node_vs_gateways_{key}_LINES.jpeg"
        path_line = os.path.join(output_dir, filename_line)
        plt.savefig(path_line, format="jpeg")
        plt.close()
        print(f"✅ Saved line plot: {path_line}")

def plot_der_per_node_vs_gateways(metrics_per_scenario, output_dir: str):
    der_data = {
        "1ed": defaultdict(dict),   # {gw: {node_id: der}}
        "10ed": defaultdict(dict)
    }

    # Extract DER values
    for scenario_name, metrics in metrics_per_scenario.items():
        match = re.search(r'(\d+)GW.*-(\d+)ed', scenario_name)
        if not match:
            continue

        num_gw = int(match.group(1))
        num_ed = int(match.group(2))
        key = "1ed" if num_ed == 1 else "10ed" if num_ed == 10 else None
        if key is None:
            continue

        for node_id, der in metrics.data_error_rate_map.items():
            der_data[key][num_gw][node_id] = der

    for key in ["1ed", "10ed"]:
        gateway_values = sorted(der_data[key].keys())
        node_ids = sorted(set().union(*[d.keys() for d in der_data[key].values()]))

        # === 📊 Bar Plot: DER per node per gateway
        fig1, ax1 = plt.subplots(figsize=(14, 6))
        width = 0.1
        bar_positions = np.arange(len(node_ids))
        num_groups = len(gateway_values)
        colors = plt.cm.tab10.colors

        for i, gw in enumerate(gateway_values):
            der_per_node = der_data[key][gw]
            heights = [der_per_node.get(nid, 0.0) for nid in node_ids]
            positions = bar_positions + (i - num_groups / 2) * width + width / 2

            bars = ax1.bar(positions, heights, width=width, color=colors[i % len(colors)], label=f"{gw} GW")

            for j, height in enumerate(heights):
                if height > 0:
                    ax1.text(
                        positions[j],
                        height + 0.01,
                        f"{height:.2f}",
                        ha='center',
                        va='bottom',
                        fontsize=7,
                        rotation=90
                    )

        ax1.set_xlabel("Node ID")
        ax1.set_ylabel("Data Error Rate (DER)")
        ax1.set_title(f"DER per Node (Grouped by Gateway Count) - {key}")
        ax1.set_xticks(bar_positions)
        ax1.set_xticklabels(node_ids)
        ax1.set_ylim(0, 1.05)
        ax1.grid(axis='y', linestyle='--', alpha=0.5)
        ax1.legend(title="Gateways", loc="upper right")
        fig1.tight_layout()

        filename_bar = f"der_per_node_vs_gateways_{key}_BARS.jpeg"
        path_bar = os.path.join(output_dir, filename_bar)
        plt.savefig(path_bar, format="jpeg")
        plt.close()
        print(f"✅ Saved bar plot: {path_bar}")

        # === 📈 Line Plot: DER evolution per node vs number of gateways
        fig2, ax2 = plt.subplots(figsize=(14, 6))
        for node_id in node_ids:
            x_vals = []
            y_vals = []
            for gw in gateway_values:
                der = der_data[key][gw].get(node_id, None)
                if der is not None:
                    x_vals.append(gw)
                    y_vals.append(der)

            if x_vals:
                ax2.plot(
                    x_vals,
                    y_vals,
                    linestyle='-',
                    marker='o',
                    linewidth=1.5,
                    alpha=0.8,
                    label=f"Node {node_id}"
                )

        ax2.set_xlabel("Number of Gateways")
        ax2.set_ylabel("Data Error Rate (DER)")
        ax2.set_title(f"DER Evolution per Node vs Gateways - {key}")
        ax2.set_xticks(gateway_values)
        ax2.set_ylim(0, 1.05)
        ax2.grid(True, linestyle='--', alpha=0.6)
        ax2.legend(title="Nodes", loc="upper right", fontsize=8, ncol=2)
        fig2.tight_layout()

        filename_line = f"der_per_node_vs_gateways_{key}_LINES.jpeg"
        path_line = os.path.join(output_dir, filename_line)
        plt.savefig(path_line, format="jpeg")
        plt.close()
        print(f"✅ Saved line plot: {path_line}")

def plot_der_vs_num_gateways(metrics_per_scenario, output_dir: str):
    """
    Plot DER evolution as the number of gateways increases,
    for 1 ED and 10 EDs separately.
    """
    import re

    der_data = {
        "1ed": {},
        "10ed": {}
    }

    # Parse DER from each scenario
    for scenario_name, metrics in metrics_per_scenario.items():
        match = re.search(r'(\d+)GW.*-(\d+)ed', scenario_name)
        if not match:
            continue

        num_gw = int(match.group(1))
        num_ed = int(match.group(2))
        key = "1ed" if num_ed == 1 else "10ed" if num_ed == 10 else None
        if key is None:
            continue

        der_values = metrics.data_error_rate_map.values()

        if der_values:
            avg_der = sum(der_values) / len(der_values)
            der_data[key][num_gw] = avg_der

    # Sort by number of gateways
    for key in der_data:
        der_data[key] = dict(sorted(der_data[key].items()))

    # Plot
    plt.figure(figsize=(10, 6))
    for label, data in der_data.items():
        plt.plot(list(data.keys()), list(data.values()), marker='o', label=label)

    plt.xlabel("Number of Gateways")
    plt.ylabel("Average Data Error Rate (DER)")
    plt.title("DER vs Number of Gateways")
    plt.grid(True, linestyle='--', alpha=0.7)
    plt.legend()
    plt.tight_layout()

    output_path = os.path.join(output_dir, "der_vs_gateways.jpeg")
    plt.savefig(output_path, format="jpeg")
    plt.close()
    print(f"✅ Saved DER vs Number of Gateways plot: {output_path}")

def plot_snir_distribution_across_scenarios(metrics_per_scenario, output_dir="plots"):
    os.makedirs(output_dir, exist_ok=True)
    plt.figure(figsize=(12, 6))
    plotted = False

    for scenario, metrics in metrics_per_scenario.items():
        if not getattr(metrics, 'snir_vectors', None):
            continue

        all_values = []
        for vec in metrics.snir_vectors:
            values = vec.get("value", [])
            if values:
                all_values.extend(values)

        if not all_values:
            continue

        bin_edges = np.histogram_bin_edges(all_values, bins='auto')
        bin_counts, _ = np.histogram(all_values, bins=bin_edges)
        bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2

        plt.bar(bin_centers, bin_counts, width=np.diff(bin_edges), alpha=0.6, edgecolor='black',
                label=f"{scenario} ({sum(bin_counts)} samples)")
        plotted = True

    if not plotted:
        print("⚠️ No SNIR data available across any scenario.")
        return

    plt.xlabel("SNIR (dB)")
    plt.ylabel("Count")
    plt.title("SNIR Distribution Across Scenarios")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "snir_distribution_across_scenarios.jpeg"))
    plt.close()

def plot_snr_margin_distribution_across_scenarios(metrics_per_scenario, output_dir="plots"):
    """
    Plot SNR Margin distribution across all scenarios in a histogram-style overlay.
    Annotate each bar with percentage and add total sample count to legend.
    """
    os.makedirs(output_dir, exist_ok=True)
    plt.figure(figsize=(12, 6))
    plotted = False

    for scenario, metrics in metrics_per_scenario.items():
        if not getattr(metrics, 'snr_margin_vectors', None):
            continue

        all_values = []
        for vec in metrics.snr_margin_vectors:
            values = vec.get("value", [])
            if values:
                all_values.extend(values)

        if not all_values:
            continue

        bin_edges = np.histogram_bin_edges(all_values, bins='auto')
        bin_counts, _ = np.histogram(all_values, bins=bin_edges)
        bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
        total = sum(bin_counts)

        # Plot bars
        bars = plt.bar(bin_centers, bin_counts, width=np.diff(bin_edges), alpha=0.6, edgecolor='black', label=f"{scenario} ({total} samples)")

        # Add % text on top of each bar
        for bar, count in zip(bars, bin_counts):
            if count > 0:
                percentage = (count / total) * 100
                plt.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), f"{percentage:.1f}%", 
                         ha='center', va='bottom', fontsize=8)

        plotted = True

    if not plotted:
        print("⚠️ No SNR Margin data available across any scenario.")
        return

    plt.xlabel("SNR Margin (dB)")
    plt.ylabel("Count")
    plt.title("SNR Margin Distribution Across Scenarios")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "snr_margin_distribution_across_scenarios.jpeg"))
    plt.close()
