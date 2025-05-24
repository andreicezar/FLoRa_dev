#!/usr/bin/env python3
"""
LoRa Network Simulation Metrics Extractor

This script processes LoRa simulation output files to extract and visualize
network performance metrics including data error rates, packet delivery ratios,
spreading factors, transmission power, and time-on-air calculations.

Author: Refactored version
Date: 2025
"""

import json
import math
import os
import re
import shutil
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import matplotlib.pyplot as plt
import numpy as np


@dataclass
class NodeMetrics:
    """Container for per-node metrics"""
    node_id: int
    packets_sent: int = 0
    packets_received: int = 0
    final_sf: Optional[int] = None
    final_tp: Optional[int] = None
    
    @property
    def packet_error_rate(self) -> float:
        """Calculate Packet Error Rate (PER)"""
        if self.packets_sent == 0:
            return 0.0
        return (self.packets_sent - self.packets_received) / self.packets_sent
    
    @property
    def packet_delivery_ratio(self) -> float:
        """Calculate Packet Delivery Ratio (PDR)"""
        if self.packets_sent == 0:
            return 0.0
        return self.packets_received / self.packets_sent
    
    @property
    def data_error_rate(self) -> float:
        """Calculate Data Error Rate (DER) - same as PER for this implementation"""
        return self.packet_error_rate


@dataclass
class GatewayMetrics:
    """Container for per-gateway metrics"""
    gateway_id: int
    packets_received: int = 0
    data_extraction_rate: float = 0.0


@dataclass
class NetworkMetrics:
    """Container for network-wide metrics"""
    server_der: float = 0.0
    sf_der: Dict[int, float] = None
    
    def __post_init__(self):
        if self.sf_der is None:
            self.sf_der = {}


class LoRaTimeOnAirCalculator:
    """Calculator for LoRa Time-on-Air"""
    
    @staticmethod
    def calculate_toa(payload_size: int, sf: int, bandwidth: int = 125000, 
                     coding_rate: int = 1, preamble: int = 8, 
                     header_enabled: bool = True) -> float:
        """
        Calculate LoRa Time-on-Air in milliseconds
        
        Args:
            payload_size: Payload size in bytes
            sf: Spreading Factor (7-12)
            bandwidth: Bandwidth in Hz (default: 125kHz)
            coding_rate: Coding rate (1-4, default: 1 for 4/5)
            preamble: Preamble length (default: 8)
            header_enabled: Whether header is enabled
            
        Returns:
            Time-on-Air in milliseconds
        """
        # Symbol time
        t_sym = (2 ** sf) / bandwidth
        
        # Low data rate optimization
        de = 1 if t_sym > 0.016 else 0
        
        # Header flag
        h = 0 if header_enabled else 1
        
        # Calculate payload symbols
        payload_symb_nb = 8 + max(
            math.ceil(
                (8 * payload_size - 4 * sf + 28 + 16 - 20 * h) / 
                (4 * (sf - 2 * de))
            ) * (coding_rate + 4),
            0
        )
        
        # Calculate times
        t_payload = payload_symb_nb * t_sym
        t_preamble = (preamble + 4.25) * t_sym
        
        return (t_preamble + t_payload) * 1000  # Convert to ms


class DataLoader:
    """Handles loading and parsing of simulation data files"""
    
    def __init__(self, input_path: Path, prefix: Optional[str] = None):
        self.input_path = Path(input_path)
        self.prefix = prefix
        
    def load_simulation_data(self) -> Tuple[List[Dict], List[Dict], int]:
        """Load vectors, scalars, and extract node count from simulation files"""
        try:
            app_file = self._find_file('_app')
            scalars_file = self._find_file('_scalars')
            
            # Load app data (vectors)
            with open(app_file, 'r') as f:
                app_data = json.load(f)
                
            # Load scalars data
            with open(scalars_file, 'r') as f:
                # Skip comment lines and evaluate the rest
                content = "\n".join(
                    line for line in f 
                    if not line.strip().startswith("#")
                )
                scalar_data = eval(content)
            
            # Extract run data
            run_id_app = next(iter(app_data))
            run_id_scalars = next(iter(scalar_data))
            
            if run_id_app != run_id_scalars:
                print(f"⚠️ Run ID mismatch: app='{run_id_app}' vs scalars='{run_id_scalars}'")
            
            vectors = app_data.get(run_id_app, {}).get("vectors", [])
            scalars = scalar_data.get(run_id_scalars, {}).get("scalars", [])
            
            # Extract node count from parameters
            node_count = self._extract_node_count(app_data, scalar_data)
            
            print(f"🔍 Returning: {len(vectors)} vectors, {len(scalars)} scalars, {node_count} nodes")
            return vectors, scalars, node_count
            
        except Exception as e:
            print(f"❌ Error in load_simulation_data: {e}")
            raise
    
    def _extract_node_count(self, app_data: Dict, scalar_data: Dict) -> int:
        """Extract numberOfNodes parameter from simulation data"""
        # First try app data parameters
        for run_id, run_data in app_data.items():
            params = run_data.get("parameters", [])
            for param in params:
                if param.get("name") == "numberOfNodes":
                    node_count = int(param.get("value", 0))
                    print(f"📊 Found numberOfNodes in app data: {node_count}")
                    return node_count
        
        # Then try scalar data parameters  
        for run_id, run_data in scalar_data.items():
            params = run_data.get("parameters", [])
            for param in params:
                if param.get("name") == "numberOfNodes":
                    node_count = int(param.get("value", 0))
                    print(f"📊 Found numberOfNodes in scalar data: {node_count}")
                    return node_count
        
        # Fallback: try to count unique node IDs from scalars
        node_ids = set()
        scalars = []
        for run_id, run_data in scalar_data.items():
            scalars = run_data.get("scalars", [])
            break
            
        for scalar in scalars:
            module = scalar.get("module", "")
            # Look for node patterns in modules
            match = re.search(r"loRaNodes\[(\d+)\]", module)
            if match:
                node_ids.add(int(match.group(1)))
        
        if node_ids:
            node_count = max(node_ids) + 1  # Assuming nodes are 0-indexed
            print(f"📊 Estimated numberOfNodes from scalar modules: {node_count}")
            return node_count
        
        # Final fallback
        print("⚠️ Could not determine numberOfNodes, using default: 20")
        return 20
    
    def _find_file(self, suffix: str) -> Path:
        """Find file with given suffix and optional prefix"""
        pattern = f"*{suffix}.json"
        candidates = list(self.input_path.glob(pattern))
        
        if self.prefix:
            candidates = [
                f for f in candidates 
                if f.name.startswith(self.prefix)
            ]
        
        if not candidates:
            raise FileNotFoundError(
                f"No file with suffix '{suffix}.json' and prefix '{self.prefix}' "
                f"found in {self.input_path}"
            )
        
        return candidates[0]


class MetricsExtractor:
    """Extracts metrics from simulation data"""
    
    def __init__(self):
        self.node_metrics: Dict[int, NodeMetrics] = {}
        self.gateway_metrics: Dict[int, GatewayMetrics] = {}
        self.network_metrics = NetworkMetrics()
        
    def extract_from_scalars(self, scalars: List[Dict]) -> None:
        """Extract metrics from scalar data"""
        for scalar in scalars:
            name = scalar.get("name", "")
            module = scalar.get("module", "")
            value = scalar.get("value")
            
            if value is None:
                continue
                
            # Extract node ID if present
            node_id = self._extract_node_id(name, module)
            gateway_id = self._extract_gateway_id(module)
            
            self._process_scalar_metric(name, module, value, node_id, gateway_id)
    
    def _extract_node_id(self, name: str, module: str) -> Optional[int]:
        """Extract node ID from name or module"""
        # From module like "loRaNodes[5]"
        match = re.search(r"loRaNodes\[(\d+)\]", module)
        if match:
            return int(match.group(1))
        
        # From name like "numReceivedFromNode 5"
        match = re.search(r"numReceivedFromNode\s*(\d+)", name)
        if match:
            return int(match.group(1))
        
        return None
    
    def _extract_gateway_id(self, module: str) -> Optional[int]:
        """Extract gateway ID from module"""
        match = re.search(r"loRaGW\[(\d+)\]", module, re.IGNORECASE)
        return int(match.group(1)) if match else None
    
    def _process_scalar_metric(self, name: str, module: str, value: Any, 
                             node_id: Optional[int], gateway_id: Optional[int]) -> None:
        """Process individual scalar metric"""
        # Node-specific metrics
        if node_id is not None:
            if node_id not in self.node_metrics:
                self.node_metrics[node_id] = NodeMetrics(node_id)
            
            node = self.node_metrics[node_id]
            
            if "finalSF" in name:
                node.final_sf = int(value)
            elif "finalTP" in name:
                node.final_tp = int(value)
            elif "sentPackets" in name:
                node.packets_sent = int(value)
            elif "numReceivedFromNode" in name:
                node.packets_received = int(value)
        
        # Gateway-specific metrics
        elif gateway_id is not None:
            if gateway_id not in self.gateway_metrics:
                self.gateway_metrics[gateway_id] = GatewayMetrics(gateway_id)
            
            gateway = self.gateway_metrics[gateway_id]
            
            if "Data Extraction Rate" in name and "LoRaGWNic" in module:
                gateway.data_extraction_rate = float(value)
            elif "LoRa_GWPacketReceived:count" in name and "packetForwarder" in module:
                gateway.packets_received = int(value)
        
        # Network-wide metrics
        elif "LoRa_NS_DER" in name:
            self.network_metrics.server_der = float(value)
        elif name.startswith("DER SF") and "networkServer" in module:
            sf_match = re.search(r"SF(\d+)", name)
            if sf_match:
                sf = int(sf_match.group(1))
                self.network_metrics.sf_der[sf] = float(value)


class VectorProcessor:
    """Processes vector data for plotting"""
    
    def __init__(self, output_path: Path, prefix: Optional[str] = None):
        self.output_path = Path(output_path)
        self.prefix = prefix
        self.estimated_node_count = None  # Will be set automatically
        self.vectors_by_type = {
            'sf': [],
            'tp': [],
            'snir': [],
            'rssi': []
        }
    
    def set_node_count(self, node_count: int):
        """Set the estimated node count from external source"""
        self.estimated_node_count = node_count
        print(f"📊 Auto-detected {node_count} nodes for vector splitting")
    
    def categorize_vectors(self, vectors: List[Dict]) -> None:
        """Categorize vectors by type"""
        for vec in vectors:
            name = vec.get("name", "").lower()
            module = vec.get("module", "")
            
            # Skip server-level vectors that don't have node-specific data
            if "networkserver" in module.lower() and ("snir" in name or "rssi" in name):
                # These are server-aggregated vectors, handle separately
                if 'snir' in name:
                    self.vectors_by_type['snir'].append(vec)
                elif 'rssi' in name:
                    self.vectors_by_type['rssi'].append(vec)
                continue
            
            if 'tp vector' in name:
                self.vectors_by_type['tp'].append(vec)
            elif 'sf vector' in name:
                self.vectors_by_type['sf'].append(vec)
            elif 'snir' in name:
                self.vectors_by_type['snir'].append(vec)
            elif 'rssi' in name:
                self.vectors_by_type['rssi'].append(vec)
    
    def split_server_vector_by_nodes(self, values: List[float], num_nodes: int) -> Dict[int, List[float]]:
        """Split server-collected vector into per-node vectors based on order"""
        if not values or num_nodes <= 0:
            return {}
        
        # Simple approach: assume values are interleaved by node
        # e.g., [node0_val1, node1_val1, node2_val1, node0_val2, node1_val2, ...]
        node_data = {i: [] for i in range(num_nodes)}
        
        for i, value in enumerate(values):
            node_id = i % num_nodes
            node_data[node_id].append(value)
        
        return node_data
    
    def plot_all_vectors(self) -> None:
        """Generate plots for all vector types"""
        for vector_type, vectors in self.vectors_by_type.items():
            if not vectors:
                continue
            
            if vector_type.lower() in ['snir', 'rssi']:
                self._plot_line_vectors(vectors, vector_type.upper())
            else:
                self._plot_histogram_vectors(vectors, vector_type.upper())
    
    def _plot_histogram_vectors(self, vectors: List[Dict], label: str) -> None:
        """Plot vectors as histograms"""
        if not vectors:
            print(f"⚠️ No {label} vectors to plot")
            return
            
        fig, ax = plt.subplots(figsize=(12, 8))
        
        # Get consistent colors
        cmap = plt.get_cmap('tab20')
        
        plotted_nodes = set()  # Track which nodes we've plotted
        
        for i, vec in enumerate(vectors):
            values = vec.get("value", [])
            if not values:
                continue
            
            node_id = self._get_node_id_from_module(vec["module"])
            
            # Skip if we've already plotted this node
            if node_id in plotted_nodes:
                continue
            plotted_nodes.add(node_id)
            
            color = cmap(node_id % 20)  # Use node_id for consistent colors
            
            # For SF/TP, ensure we show the correct range
            if label.upper() == 'SF':
                # SF should be integers 7-12
                bins = np.arange(6.5, 13.5, 1)  # Bins centered on integers 7-12
                ax.hist(values, bins=bins, alpha=0.7, 
                       label=f"Node {node_id}", color=color)
                ax.set_xticks(range(7, 13))
            elif label.upper() == 'TP':
                # TP should be discrete values: 2, 5, 8, 11, 14 dBm
                bins = np.arange(1, 16, 1)
                ax.hist(values, bins=bins, alpha=0.7, 
                       label=f"Node {node_id}", color=color)
                ax.set_xticks([2, 5, 8, 11, 14])
            else:
                ax.hist(values, bins=20, alpha=0.7, 
                       label=f"Node {node_id}", color=color)
        
        ax.set_title(f"{label} Distribution per Node")
        ax.set_xlabel(label)
        ax.set_ylabel("Frequency")
        
        # Only show legend if we have reasonable number of nodes
        if len(plotted_nodes) <= 10:
            ax.legend(fontsize='small', loc='best')
        else:
            ax.text(0.02, 0.98, f"{len(plotted_nodes)} nodes plotted", 
                   transform=ax.transAxes, verticalalignment='top')
        
        ax.grid(True, alpha=0.3)
        
        self._save_plot(fig, f"{label.lower()}_histogram")
    
    def _plot_line_vectors(self, vectors: List[Dict], label: str) -> None:
        """Plot vectors as line plots"""
        if not vectors:
            print(f"⚠️ No {label} vectors to plot")
            return
            
        fig, ax = plt.subplots(figsize=(12, 8))
        
        # Handle server-collected per-node data (common in LoRa simulations)
        if label.upper() in ['SNIR', 'RSSI']:
            server_vectors = []
            node_vectors = []
            
            for vec in vectors:
                module = vec.get("module", "")
                name = vec.get("name", "").lower()
                
                if "networkserver" in module.lower() and "per node" in name:
                    server_vectors.append(vec)
                else:
                    node_vectors.append(vec)
            
            # If we have server-collected per-node data, try to split it
            if server_vectors and self.estimated_node_count:
                vec = server_vectors[0]  # Use first vector
                values = vec.get("value", [])
                
                if values:
                    num_nodes = self.estimated_node_count
                    
                    # Check if we should attempt splitting
                    if len(values) >= num_nodes * 2:  # At least 2 values per node
                        print(f"📊 Splitting {label} server data into {num_nodes} nodes ({len(values)} total values)")
                        node_data = self.split_server_vector_by_nodes(values, num_nodes)
                        
                        cmap = plt.get_cmap('tab20')
                        plotted_any = False
                        
                        for node_id, node_values in node_data.items():
                            if node_values:  # Only plot if node has data
                                color = cmap(node_id % 20)
                                ax.plot(node_values, label=f"Node {node_id}", 
                                       color=color, alpha=0.7, linewidth=1)
                                plotted_any = True
                        
                        if plotted_any:
                            ax.set_title(f"{label} over Time per Node (Auto-Split from Server Data)")
                            ax.set_xlabel("Time Index")
                            ax.set_ylabel(f"{label} (dB)")
                            
                            # Smart legend handling
                            if num_nodes <= 15:
                                ax.legend(fontsize='small', loc='best', ncol=3)
                            else:
                                ax.text(0.02, 0.98, f"{num_nodes} nodes plotted", 
                                       transform=ax.transAxes, verticalalignment='top',
                                       bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8))
                            
                            ax.grid(True, alpha=0.3)
                            self._save_plot(fig, f"{label.lower()}_split_timeline")
                            return
                    
                    # Fallback: Plot as combined timeline if splitting doesn't make sense
                    ax.plot(values, label=f"All Nodes {label}", 
                           color='blue', alpha=0.7, linewidth=0.5)
                    
                    ax.set_title(f"{label} over Time (Server-Collected from All Nodes)")
                    ax.set_xlabel("Sample Index") 
                    ax.set_ylabel(f"{label} (dB)")
                    ax.legend()
                    ax.grid(True, alpha=0.3)
                    
                    # Add some statistics
                    if len(values) > 0:
                        ax.text(0.02, 0.98, 
                               f"Samples: {len(values)}\nNodes: {self.estimated_node_count or 'Unknown'}\nMin: {min(values):.2f}\nMax: {max(values):.2f}", 
                               transform=ax.transAxes, verticalalignment='top',
                               bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8))
                
                self._save_plot(fig, f"{label.lower()}_combined_timeline")
                return
        
        # Handle individual node vectors - assign node IDs based on order in file
        plotted_count = 0
        cmap = plt.get_cmap('tab20')
        
        for i, vec in enumerate(vectors):
            values = vec.get("value", [])
            if not values:
                continue
            
            # Try to extract node ID from module first
            node_id = self._get_node_id_from_module(vec["module"])
            
            # If no node ID found from module, use file order as node ID
            if node_id == -1 or node_id == 0:
                node_id = i  # Use index as node ID
            
            color = cmap(node_id % 20)
            ax.plot(values, label=f"Node {node_id}", 
                   color=color, alpha=0.8, linewidth=1)
            plotted_count += 1
        
        if plotted_count == 0:
            plt.close(fig)
            print(f"⚠️ No valid data found for {label}")
            return
        
        ax.set_title(f"{label} over Time per Node")
        ax.set_xlabel("Time Steps")
        ax.set_ylabel(f"{label} (dB)")
        
        # Only show legend if reasonable number of nodes
        if plotted_count <= 15:
            ax.legend(fontsize='small', loc='best', ncol=2)
        else:
            ax.text(0.02, 0.98, f"{plotted_count} nodes plotted", 
                   transform=ax.transAxes, verticalalignment='top',
                   bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8))
        
        ax.grid(True, alpha=0.3)
        self._save_plot(fig, f"{label.lower()}_timeline")
    
    def _get_node_id_from_module(self, module: str) -> int:
        """Extract node ID from module string"""
        # Try different patterns for node-specific modules
        patterns = [
            r"loRaNodes\[(\d+)\]",     # Standard pattern: loRaNodes[X]
            r"node\[(\d+)\]",          # Alternative pattern: node[X]
            r"Node(\d+)",              # Another pattern: NodeX
            r"node(\d+)"               # Lowercase variant: nodeX
        ]
        
        for pattern in patterns:
            match = re.search(pattern, module, re.IGNORECASE)
            if match:
                return int(match.group(1))
        
        # Handle server-level modules - don't print warning for expected server modules
        if "networkserver" in module.lower():
            return -1  # Use -1 to indicate server-level data
        
        # Only print warning for truly unexpected module patterns
        print(f"⚠️ Could not extract node ID from module: {module}")
        return 0
    
    def _save_plot(self, fig: plt.Figure, plot_type: str) -> None:
        """Save plot to file"""
        filename = f"{self.prefix}_{plot_type}.png" if self.prefix else f"{plot_type}.png"
        filepath = self.output_path / filename
        
        fig.tight_layout()
        fig.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close(fig)
        print(f"✅ Saved plot: {filename}")


class MetricsPlotter:
    """Creates various metric plots"""
    
    def __init__(self, output_path: Path, prefix: Optional[str] = None):
        self.output_path = Path(output_path)
        self.prefix = prefix
    
    def plot_data_error_rate(self, node_metrics: Dict[int, NodeMetrics]) -> None:
        """Plot Data Error Rate per node"""
        if not node_metrics:
            print("⚠️ No node metrics available for DER plot")
            return
        
        # Prepare data
        node_ids = sorted(node_metrics.keys())
        der_values = [node_metrics[nid].data_error_rate for nid in node_ids]
        
        # Create plot
        fig, ax = plt.subplots(figsize=(12, 8))
        
        colors = plt.cm.tab20(np.linspace(0, 1, len(node_ids)))
        bars = ax.bar(node_ids, der_values, color=colors)
        
        # ===== FIX: Force integer ticks for node IDs =====
        ax.set_xticks(node_ids)  # Only show actual node IDs
        ax.set_xticklabels([str(nid) for nid in node_ids])  # Ensure they're strings
        
        # Add value labels on bars
        for node_id, der in zip(node_ids, der_values):
            ax.text(node_id, der + max(der_values) * 0.01, f"{der:.4f}",
                   ha='center', va='bottom', fontsize=9)
        
        ax.set_xlabel("Node ID")
        ax.set_ylabel("Data Error Rate (DER)")
        ax.set_title("Data Error Rate per Node")
        ax.grid(True, axis='y', alpha=0.3)
        ax.set_ylim(0, max(der_values) * 1.15 if der_values else 0.1)
        
        # ===== ADDITIONAL: Ensure x-axis shows all integers and proper limits =====
        if len(node_ids) > 1:
            ax.set_xlim(min(node_ids) - 0.5, max(node_ids) + 0.5)
        
        # ===== FORCE integer formatting on x-axis =====
        from matplotlib.ticker import MaxNLocator
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        
        self._save_plot(fig, "data_error_rate_per_node")
    
    def _save_plot(self, fig: plt.Figure, plot_name: str) -> None:
        """Save plot to file"""
        filename = f"{self.prefix}_{plot_name}.png" if self.prefix else f"{plot_name}.png"
        filepath = self.output_path / filename
        
        fig.tight_layout()
        fig.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close(fig)
        print(f"✅ Saved plot: {filename}")


class ReportGenerator:
    """Generates text reports"""
    
    def __init__(self, output_path: Path, prefix: Optional[str] = None):
        self.output_path = Path(output_path)
        self.prefix = prefix
        self.report_lines = []
    
    def generate_report(self, node_metrics: Dict[int, NodeMetrics],
                       gateway_metrics: Dict[int, GatewayMetrics],
                       network_metrics: NetworkMetrics) -> None:
        """Generate comprehensive report"""
        self.report_lines = []
        
        self._add_header()
        self._add_node_metrics_summary(node_metrics)
        self._add_gateway_metrics_summary(gateway_metrics)
        self._add_network_metrics_summary(network_metrics)
        self._add_time_on_air_summary(node_metrics)
        
        self._save_report()
    
    def _add_header(self) -> None:
        """Add report header"""
        self.report_lines.extend([
            "=" * 60,
            "LoRa Network Simulation Metrics Report",
            "=" * 60,
            ""
        ])
    
    def _add_node_metrics_summary(self, node_metrics: Dict[int, NodeMetrics]) -> None:
        """Add node metrics summary"""
        self.report_lines.extend([
            "📊 NODE METRICS SUMMARY",
            "-" * 80,
            f"{'Node':<6} {'Sent':<8} {'Recv':<8} {'DER':<8} {'PER':<8} {'PDR':<8} {'SF':<4} {'TP':<4}",
            "-" * 80
        ])
        
        for node_id in sorted(node_metrics.keys()):
            node = node_metrics[node_id]
            sf_str = str(node.final_sf) if node.final_sf is not None else "N/A"
            tp_str = str(node.final_tp) if node.final_tp is not None else "N/A"
            
            self.report_lines.append(
                f"{node_id:<6} {node.packets_sent:<8} {node.packets_received:<8} "
                f"{node.data_error_rate:<8.4f} {node.packet_error_rate:<8.4f} "
                f"{node.packet_delivery_ratio:<8.4f} {sf_str:<4} {tp_str:<4}"
            )
        
        self.report_lines.append("")
    
    def _add_gateway_metrics_summary(self, gateway_metrics: Dict[int, GatewayMetrics]) -> None:
        """Add gateway metrics summary"""
        if not gateway_metrics:
            return
        
        self.report_lines.extend([
            "📡 GATEWAY METRICS SUMMARY",
            "-" * 50,
            f"{'Gateway':<10} {'Packets Received':<20} {'DER':<10}",
            "-" * 50
        ])
        
        for gw_id in sorted(gateway_metrics.keys()):
            gw = gateway_metrics[gw_id]
            self.report_lines.append(
                f"{gw_id:<10} {gw.packets_received:<20} {gw.data_extraction_rate:<10.5f}"
            )
        
        self.report_lines.append("")
    
    def _add_network_metrics_summary(self, network_metrics: NetworkMetrics) -> None:
        """Add network-wide metrics summary"""
        self.report_lines.extend([
            "🌐 NETWORK METRICS SUMMARY",
            "-" * 40,
            f"Server DER: {network_metrics.server_der:.5f}",
            ""
        ])
        
        if network_metrics.sf_der:
            self.report_lines.append("DER per Spreading Factor:")
            for sf in sorted(network_metrics.sf_der.keys()):
                der = network_metrics.sf_der[sf]
                self.report_lines.append(f"  SF{sf}: {der:.5f}")
            self.report_lines.append("")
    
    def _add_time_on_air_summary(self, node_metrics: Dict[int, NodeMetrics]) -> None:
        """Add time-on-air calculations"""
        self.report_lines.extend([
            "⏱️ TIME ON AIR SUMMARY (20-byte payload)",
            "-" * 60,
            f"{'Node':<6} {'SF':<4} {'Packets':<10} {'ToA/Packet (ms)':<16} {'Total ToA (ms)':<15}",
            "-" * 60
        ])
        
        calculator = LoRaTimeOnAirCalculator()
        total_toa = 0.0
        
        for node_id in sorted(node_metrics.keys()):
            node = node_metrics[node_id]
            
            if node.final_sf is None or node.packets_sent == 0:
                continue
            
            toa_per_packet = calculator.calculate_toa(20, node.final_sf)
            toa_total = toa_per_packet * node.packets_sent
            total_toa += toa_total
            
            self.report_lines.append(
                f"{node_id:<6} {node.final_sf:<4} {node.packets_sent:<10} "
                f"{toa_per_packet:<16.2f} {toa_total:<15.2f}"
            )
        
        self.report_lines.extend([
            "-" * 60,
            f"Total Network Time on Air: {total_toa:.2f} ms",
            ""
        ])
    
    def _save_report(self) -> None:
        """Save report to file"""
        filename = f"report_{self.prefix}.txt" if self.prefix else "report.txt"
        filepath = self.output_path / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('\n'.join(self.report_lines))
        
        print(f"📄 Report saved to: {filepath}")


class LoRaMetricsExtractor:
    """Main class for extracting and processing LoRa simulation metrics"""
    
    def __init__(self, input_path: str, output_path: str, prefix: Optional[str] = None):
        self.input_path = Path(input_path)
        self.output_path = Path(output_path)
        self.prefix = prefix
        
        # Create output directory
        self.output_path.mkdir(parents=True, exist_ok=True)
        
        # Initialize components
        self.data_loader = DataLoader(self.input_path, prefix)
        self.metrics_extractor = MetricsExtractor()
        self.vector_processor = VectorProcessor(self.output_path, prefix)
        self.metrics_plotter = MetricsPlotter(self.output_path, prefix)
        self.report_generator = ReportGenerator(self.output_path, prefix)
    
    def process(self) -> Dict[str, Any]:
        """Main processing method"""
        print(f"📂 Processing: {self.input_path}, prefix: {self.prefix}")
        
        try:
            # Load data including node count
            print("🔍 Loading simulation data...")
            result = self.data_loader.load_simulation_data()
            print(f"🔍 Got result with {len(result)} items")
            
            vectors, scalars, node_count = result
            print(f"🔍 Successfully unpacked: {len(vectors)} vectors, {len(scalars)} scalars, {node_count} nodes")
            
            # Pass node count to vector processor
            self.vector_processor.set_node_count(node_count)
            
            # Extract metrics
            self.metrics_extractor.extract_from_scalars(scalars)
            
            # Process vectors
            self.vector_processor.categorize_vectors(vectors)
            self.vector_processor.plot_all_vectors()
            
            # Create metric plots
            self.metrics_plotter.plot_data_error_rate(
                self.metrics_extractor.node_metrics
            )
            
            # Generate report
            self.report_generator.generate_report(
                self.metrics_extractor.node_metrics,
                self.metrics_extractor.gateway_metrics,
                self.metrics_extractor.network_metrics
            )
            
            return self._get_results()
            
        except Exception as e:
            print(f"❌ Error in process: {e}")
            raise
    
    def _get_results(self) -> Dict[str, Any]:
        """Get processed results"""
        return {
            'node_metrics': self.metrics_extractor.node_metrics,
            'gateway_metrics': self.metrics_extractor.gateway_metrics,
            'network_metrics': self.metrics_extractor.network_metrics,
            'vectors_by_type': self.vector_processor.vectors_by_type,
            'node_count': self.vector_processor.estimated_node_count
        }


class MultiScenarioProcessor:
    """Processes multiple simulation scenarios"""
    
    def __init__(self, scenario_folders: List[str]):
        self.scenario_folders = [Path(folder) for folder in scenario_folders]
        self.results = {}
    
    def process_all(self) -> Dict[str, Any]:
        """Process all scenarios"""
        for folder in self.scenario_folders:
            if not folder.is_dir():
                print(f"❌ Folder does not exist: {folder}")
                continue
            
            prefixes = self._get_file_prefixes(folder)
            if not prefixes:
                print(f"⚠️ No valid *_app.json files found in {folder}")
                continue
            
            for prefix in prefixes:
                print(f"\n📂 Processing scenario: {folder.name}, set: {prefix}")
                
                output_path = folder / "plots" / prefix
                extractor = LoRaMetricsExtractor(folder, output_path, prefix)
                
                try:
                    results = extractor.process()
                    scenario_id = f"{folder.name}__{prefix}"
                    self.results[scenario_id] = results
                except Exception as e:
                    print(f"❌ Error processing {folder.name}/{prefix}: {e}")
        
        return self.results
    
    def _get_file_prefixes(self, folder: Path) -> List[str]:
        """Get all file prefixes in folder"""
        app_files = list(folder.glob('*_app.json'))
        prefixes = sorted(set(
            f.name.replace('_app.json', '') 
            for f in app_files
        ))
        return prefixes


def main():
    """Main entry point"""
    # Get base directories
    base_dir = Path(__file__).parent
    parent_dir = base_dir.parent
    
    # Parse command line arguments
    selected_folders = sys.argv[1:] if len(sys.argv) > 1 else []
    
    # Find scenario folders
    scenario_folders = []
    for root in parent_dir.rglob("export_json*"):
        if root.is_dir():
            if not selected_folders or any(sf in root.name for sf in selected_folders):
                scenario_folders.append(str(root))
    
    if not scenario_folders:
        print("⚠️ No scenario directories found.")
        return
    
    print('📂 Selected scenario directories:')
    for folder in scenario_folders:
        print(f'📁 {folder}')
    
    # Clean up existing plots folders
    for folder_str in scenario_folders:
        folder = Path(folder_str)
        plots_folder = folder / "plots"
        if plots_folder.exists():
            print(f"🧹 Cleaning up: {plots_folder}")
            shutil.rmtree(plots_folder)
    
    # Process all scenarios
    processor = MultiScenarioProcessor(scenario_folders)
    results = processor.process_all()
    
    print(f"\n✅ Processing complete! Processed {len(results)} scenario sets.")


if __name__ == "__main__":
    main()