import json
import os
import re
import argparse
from pathlib import Path
from collections import defaultdict, Counter
from typing import Dict, List, Any, Tuple
import pandas as pd

class LoRaDataExtractor:
    def __init__(self):
        self.extracted_data = {}
        self.node_patterns = {
            'end_node': re.compile(r'loRaNodes\[(\d+)\]'),
            'gateway': re.compile(r'networkServer|gateway'),
            'app_server': re.compile(r'appServer'),
            'network': re.compile(r'^LoRaNetworkTest$')
        }
    
    def identify_node_type(self, module_path: str) -> Tuple[str, int]:
        """Identify if module belongs to end node, gateway, etc. and extract node ID."""
        end_node_match = self.node_patterns['end_node'].search(module_path)
        if end_node_match:
            node_id = int(end_node_match.group(1))
            return 'end_node', node_id
        if self.node_patterns['gateway'].search(module_path):
            return 'gateway', 0
        if self.node_patterns['app_server'].search(module_path):
            return 'app_server', 0
        if self.node_patterns['network'].search(module_path):
            return 'network', 0
        return 'unknown', -1
    
    def extract_vectors(self, data: Dict) -> Dict[str, List]:
        """Extract vector data organized by node type and ID."""
        vectors_by_node = defaultdict(lambda: defaultdict(list))
        run_key = list(data.keys())[0]
        vectors = data[run_key].get('vectors', [])
        for vector in vectors:
            module = vector.get('module', '')
            node_type, node_id = self.identify_node_type(module)
            vector_data = {
                'module': module,
                'name': vector.get('name', ''),
                'time': vector.get('time', []),
                'value': vector.get('value', []),
                'eventnumber': vector.get('eventnumber', []),
                'data_points': len(vector.get('time', []))
            }
            vectors_by_node[node_type][node_id].append(vector_data)
        return dict(vectors_by_node)
    
    def extract_scalars(self, data: Dict) -> Dict[str, List]:
        """Extract scalar data organized by node type and ID."""
        scalars_by_node = defaultdict(lambda: defaultdict(list))
        run_key = list(data.keys())[0]
        scalars = data[run_key].get('scalars', [])
        for scalar in scalars:
            module = scalar.get('module', '')
            node_type, node_id = self.identify_node_type(module)
            scalar_data = {
                'module': module,
                'name': scalar.get('name', ''),
                'value': scalar.get('value'),
                'attributes': scalar.get('attributes', {})
            }
            scalars_by_node[node_type][node_id].append(scalar_data)
        return dict(scalars_by_node)
    
    def extract_histograms(self, data: Dict) -> Dict[str, List]:
        """Extract histogram data organized by node type and ID."""
        histograms_by_node = defaultdict(lambda: defaultdict(list))
        run_key = list(data.keys())[0]
        histograms = data[run_key].get('histograms', [])
        for histogram in histograms:
            module = histogram.get('module', '')
            node_type, node_id = self.identify_node_type(module)
            histogram_data = {
                'module': module,
                'name': histogram.get('name', ''),
                'count': histogram.get('count'),
                'mean': histogram.get('mean'),
                'stddev': histogram.get('stddev'),
                'min': histogram.get('min'),
                'max': histogram.get('max'),
                'sum': histogram.get('sum'),
                'sqrsum': histogram.get('sqrsum'),
                'binedges': histogram.get('binedges', []),
                'binvalues': histogram.get('binvalues', []),
                'attributes': histogram.get('attributes', {})
            }
            histograms_by_node[node_type][node_id].append(histogram_data)
        return dict(histograms_by_node)
    
    def extract_parameters(self, data: Dict) -> Dict[str, List]:
        """Extract parameter data organized by node type and ID."""
        parameters_by_node = defaultdict(lambda: defaultdict(list))
        run_key = list(data.keys())[0]
        parameters = data[run_key].get('parameters', [])
        for parameter in parameters:
            module = parameter.get('module', '')
            node_type, node_id = self.identify_node_type(module)
            parameter_data = {
                'module': module,
                'name': parameter.get('name', ''),
                'value': parameter.get('value'),
                'attributes': parameter.get('attributes', {})
            }
            parameters_by_node[node_type][node_id].append(parameter_data)
        return dict(parameters_by_node)
    
    def count_nodes(self, data: Dict) -> Dict[str, int]:
        """Count number of each node type."""
        node_counts = defaultdict(set)
        run_key = list(data.keys())[0]
        run_data = data[run_key]
        for data_type in ['vectors', 'scalars', 'histograms', 'parameters']:
            if data_type in run_data:
                for item in run_data[data_type]:
                    module = item.get('module', '')
                    node_type, node_id = self.identify_node_type(module)
                    if node_type != 'unknown':
                        node_counts[node_type].add(node_id)
        return {node_type: len(node_ids) for node_type, node_ids in node_counts.items()}
    
    def process_file(self, filepath: str) -> Dict[str, Any]:
        """Process a single JSON file and extract all data."""
        try:
            with open(filepath, 'r', encoding='utf-8') as file:
                data = json.load(file)
            filename = os.path.basename(filepath)
            file_type = None
            if 'vectors' in filename:
                file_type = 'vectors'
            elif 'scalars' in filename:
                file_type = 'scalars'
            elif 'histograms' in filename:
                file_type = 'histograms'
            elif 'parameters' in filename:
                file_type = 'parameters'
            extracted = {}
            if file_type == 'vectors':
                extracted['vectors'] = self.extract_vectors(data)
            elif file_type == 'scalars':
                extracted['scalars'] = self.extract_scalars(data)
            elif file_type == 'histograms':
                extracted['histograms'] = self.extract_histograms(data)
            elif file_type == 'parameters':
                extracted['parameters'] = self.extract_parameters(data)
            extracted['node_counts'] = self.count_nodes(data)
            run_key = list(data.keys())[0]
            extracted['metadata'] = {
                'filename': filename,
                'file_type': file_type,
                'run_id': run_key,
                'attributes': data[run_key].get('attributes', {}),
                'config_count': len(data[run_key].get('config', [])),
                'file_size': os.path.getsize(filepath)
            }
            return extracted
        except Exception as e:
            return {
                'filename': os.path.basename(filepath),
                'error': f"Error processing file: {str(e)}"
            }
    
    def analyze_node_metrics(self, extracted_data: Dict) -> Dict[str, Any]:
        """Analyze what metrics are available per node type."""
        analysis = {
            'end_node_metrics': defaultdict(set),
            'gateway_metrics': defaultdict(set),
            'network_metrics': defaultdict(set),
            'app_server_metrics': defaultdict(set)
        }
        for file_data in extracted_data.values():
            if 'error' in file_data:
                continue
            for data_type in ['vectors', 'scalars', 'histograms', 'parameters']:
                if data_type in file_data:
                    node_data = file_data[data_type]
                    for node_type, nodes in node_data.items():
                        for node_id, metrics in nodes.items():
                            for metric in metrics:
                                metric_name = metric.get('name', '')
                                if node_type == 'end_node':
                                    analysis['end_node_metrics'][data_type].add(metric_name)
                                elif node_type == 'gateway':
                                    analysis['gateway_metrics'][data_type].add(metric_name)
                                elif node_type == 'network':
                                    analysis['network_metrics'][data_type].add(metric_name)
                                elif node_type == 'app_server':
                                    analysis['app_server_metrics'][data_type].add(metric_name)
        for node_type in analysis:
            for data_type in analysis[node_type]:
                analysis[node_type][data_type] = sorted(list(analysis[node_type][data_type]))
        return dict(analysis)
    
    def process_scenario_files(self, file_paths: List[str]) -> Dict[str, Any]:
        """Process all files for a scenario and provide comprehensive analysis."""
        print(f"Processing {len(file_paths)} files...")
        extracted_data = {}
        for filepath in file_paths:
            if not os.path.exists(filepath):
                print(f"Warning: File not found - {filepath}")
                continue
            print(f"  - {os.path.basename(filepath)}")
            file_data = self.process_file(filepath)
            if 'error' not in file_data:
                # note: keys are per-type; last one wins if duplicates exist
                extracted_data[file_data['metadata']['file_type']] = file_data
            else:
                print(f"Error: {file_data['error']}")
        metrics_analysis = self.analyze_node_metrics(extracted_data)
        total_node_counts = defaultdict(set)
        for file_data in extracted_data.values():
            if 'node_counts' in file_data:
                for node_type, _ in file_data['node_counts'].items():
                    for data_type in ['vectors', 'scalars', 'histograms', 'parameters']:
                        if data_type in file_data and node_type in file_data[data_type]:
                            for node_id in file_data[data_type][node_type].keys():
                                total_node_counts[node_type].add(node_id)
        final_node_counts = {node_type: len(node_ids) for node_type, node_ids in total_node_counts.items()}
        results = {
            'extracted_data': extracted_data,
            'metrics_analysis': metrics_analysis,
            'node_counts': final_node_counts,
            'files_processed': len(extracted_data),
            'total_end_nodes': final_node_counts.get('end_node', 0),
            'total_gateways': final_node_counts.get('gateway', 0),
            'summary': self.create_summary(extracted_data, final_node_counts)
        }
        return results
    
    def create_summary(self, extracted_data: Dict, node_counts: Dict) -> Dict[str, Any]:
        """Create a summary of the extracted data."""
        summary = {
            'data_types_found': list(extracted_data.keys()),
            'node_counts': node_counts,
            'data_points': {}
        }
        for file_type, file_data in extracted_data.items():
            if file_type in ['vectors', 'scalars', 'histograms', 'parameters']:
                total_items = 0
                if file_type in file_data:
                    for node_type, nodes in file_data[file_type].items():
                        for node_id, items in nodes.items():
                            total_items += len(items)
                summary['data_points'][file_type] = total_items
        return summary
    
    def print_results(self, results: Dict[str, Any], title: str = None):
        """Print a formatted summary of the results."""
        print("\n" + "="*60)
        print("LORA SIMULATION DATA EXTRACTION RESULTS")
        if title:
            print(f"Scenario: {title}")
        print("="*60)
        print(f"\nNODE INVENTORY:")
        print(f"- End Nodes: {results['total_end_nodes']}")
        print(f"- Gateways: {results['total_gateways']}")
        for node_type, count in results['node_counts'].items():
            if node_type not in ['end_node', 'gateway']:
                print(f"- {node_type.title()}: {count}")
        print(f"\nDATA SUMMARY:")
        summary = results['summary']
        for data_type, count in summary['data_points'].items():
            print(f"- {data_type.title()}: {count:,} items")
        print(f"\nMETRICS BY NODE TYPE:")
        metrics = results['metrics_analysis']
        for node_category, node_metrics in metrics.items():
            if any(node_metrics.values()):
                print(f"\n{node_category.upper().replace('_', ' ')}:")
                for data_type, metric_names in node_metrics.items():
                    if metric_names:
                        print(f"  {data_type.title()}: {len(metric_names)} unique metrics")
                        examples = metric_names[:3]
                        if len(examples) > 0:
                            print(f"    Examples: {', '.join(examples)}")
                        if len(metric_names) > 3:
                            print(f"    ... and {len(metric_names) - 3} more")

def discover_json_files(directory: Path, recursive: bool, pattern: str) -> List[str]:
    if recursive:
        files = sorted(str(p) for p in directory.rglob(pattern) if p.is_file())
    else:
        files = sorted(str(p) for p in directory.glob(pattern) if p.is_file())
    return files

def group_by_scenario_base(files: List[str]) -> Dict[str, List[str]]:
    """
    Group files by base like 'scenario-05-baseline-low-traffic-s0'.
    Accepts suffixes: app_vectors, vectors, scalars, histograms, parameters.
    """
    groups: Dict[str, List[str]] = defaultdict(list)
    rx = re.compile(r'^(?P<base>.+-s\d+)_(?P<kind>(?:app_)?vectors|scalars|histograms|parameters)\.json$')
    for f in files:
        name = os.path.basename(f)
        m = rx.match(name)
        if m:
            groups[m.group('base')].append(f)
    return groups

def main():
    parser = argparse.ArgumentParser(description="Extract & summarize LoRa JSON exports for all scenarios in a folder.")
    parser.add_argument("-d", "--dir", default=None, help="Folder to scan (default: the folder containing this script)")
    parser.add_argument("-r", "--recursive", action="store_true", help="Scan subfolders recursively")
    parser.add_argument("-p", "--pattern", default="*.json", help="Glob pattern to match files (default: *.json)")
    parser.add_argument("-o", "--out", default=None, help="Folder to write per-scenario extracted JSON (default: input folder)")
    args = parser.parse_args()

    base_dir = Path(args.dir).resolve() if args.dir else Path(__file__).resolve().parent
    out_dir = Path(args.out).resolve() if args.out else base_dir

    all_json = discover_json_files(base_dir, args.recursive, args.pattern)
    if not all_json:
        print(f"⚠️  No JSON files matching '{args.pattern}' in {base_dir}")
        return

    groups = group_by_scenario_base(all_json)
    if not groups:
        print(f"⚠️  Found {len(all_json)} JSON files but none matched the naming '*-sX_{type}.json'.")
        return

    print("🔍 LoRa JSON extractor")
    print("==================================================")
    print(f"📂 Base directory: {base_dir}")
    print(f"🧩 Scenarios found: {len(groups)}")
    print("")

    extractor = LoRaDataExtractor()

    grand_totals = Counter()
    for base, files in sorted(groups.items()):
        print(f"▶ Scenario: {base}  ({len(files)} files)")
        results = extractor.process_scenario_files(sorted(files))
        extractor.print_results(results, title=base)

        # Save per-scenario extracted data
        out_path = out_dir / f"{base}_extracted.json"
        # Convert defaultdicts to regular dicts for JSON serialization
        def convert_defaultdicts(obj):
            if isinstance(obj, defaultdict):
                return dict(obj)
            elif isinstance(obj, dict):
                return {k: convert_defaultdicts(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_defaultdicts(item) for item in obj]
            else:
                return obj
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(convert_defaultdicts(results), f, indent=2)
        print(f"💾 Saved: {out_path}\n")

        # accumulate totals
        grand_totals['scenarios'] += 1
        grand_totals['files'] += results.get('files_processed', 0)
        grand_totals['end_nodes'] += results.get('total_end_nodes', 0)
        grand_totals['gateways'] += results.get('total_gateways', 0)

    print("==================================================")
    print(f"✅ Done. Scenarios processed: {grand_totals['scenarios']}, files used: {grand_totals['files']}")
    print(f"   Total end nodes (sum of maxima across scenarios): {grand_totals['end_nodes']}")
    print(f"   Total gateways  (sum of maxima across scenarios): {grand_totals['gateways']}")
    print("")

if __name__ == "__main__":
    main()
