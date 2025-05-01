import os
import glob
import matplotlib.pyplot as plt
import sys
from collections import defaultdict
from plotting_helper import LoRaSimulationAnalyzer, plot_data_error_rate_per_node_across_scenarios,plot_data_extraction_rate_per_gateway,\
                                                    plot_spreading_factor_per_node_across_scenarios, plot_snir_distribution_across_scenarios,\
                                                    plot_rssi_distribution_across_scenarios, plot_snr_margin_distribution_across_scenarios,\
                                                    plot_der_vs_num_gateways, plot_der_per_node_vs_gateways, plot_der_per_node_vs_gateways
import numpy as np
from html_dashboard_helper import generate_html_dashboard
# === 🔧 GLOBAL CONFIGURATION ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EXPORT_JSON_DIR = os.path.join(BASE_DIR, "..", "export_json")
OUTPUT_PLOT_DIR = os.path.join(BASE_DIR, "plots")
REQUIRED_SUFFIXES = ["app", "scalars", "parameters", "histograms"]

def main():
    os.makedirs(OUTPUT_PLOT_DIR, exist_ok=True)

    # === 🔍 Discover scenarios ===
    all_json_files = glob.glob(os.path.join(EXPORT_JSON_DIR, "*.json"))
    scenario_files = defaultdict(dict)

    for filepath in all_json_files:
        filename = os.path.basename(filepath)
        for suffix in REQUIRED_SUFFIXES:
            if f"_{suffix}.json" in filename:
                key = filename.replace(f"_{suffix}.json", "")
                scenario_files[key][suffix] = filepath
                break

    metrics_per_scenario = {}

    # === 📊 Analyze each scenario ===
    for scenario_name, files in sorted(scenario_files.items()):
        print(f"\n=== 📁 Scenario: {scenario_name} ===")
        if not all(k in files for k in REQUIRED_SUFFIXES):
            print(f"⚠️ Skipping {scenario_name} (missing files)")
            continue

        analyzer = LoRaSimulationAnalyzer()
        analyzer.load_data(
            all_apps_path=files["app"],
            all_histograms_path=files["histograms"],
            all_scalars_path=files["scalars"],
            all_parameters_path=files["parameters"],
        )

        analyzer.EXPORT_DIR = os.path.join(OUTPUT_PLOT_DIR, scenario_name)
        os.makedirs(analyzer.EXPORT_DIR, exist_ok=True)
        
        # ✅ Store metrics
        summary = analyzer.compute_metrics_summary(scenario_name)
        metrics_per_scenario[scenario_name] = summary

        analyzer.plot_all()
        analyzer.print_report(output_path=os.path.join(analyzer.EXPORT_DIR, "report.txt"))


    # Plot data extraction rate per gateway (grouped by scenario)
    plot_data_extraction_rate_per_gateway(metrics_per_scenario, output_dir=OUTPUT_PLOT_DIR)

    # === 📈 Cross-scenario DER/ERR plotting ===
    plot_data_error_rate_per_node_across_scenarios(metrics_per_scenario, output_dir=OUTPUT_PLOT_DIR)

    # Plot Spreading Factor per gateway (grouped by scenario)
    plot_spreading_factor_per_node_across_scenarios(metrics_per_scenario, output_dir=OUTPUT_PLOT_DIR)

    plot_snir_distribution_across_scenarios(metrics_per_scenario, output_dir=OUTPUT_PLOT_DIR)
    plot_rssi_distribution_across_scenarios(metrics_per_scenario, output_dir=OUTPUT_PLOT_DIR)
    plot_snr_margin_distribution_across_scenarios(metrics_per_scenario, output_dir=OUTPUT_PLOT_DIR)
    plot_der_vs_num_gateways(metrics_per_scenario, output_dir=OUTPUT_PLOT_DIR)
    plot_der_per_node_vs_gateways(metrics_per_scenario, output_dir=OUTPUT_PLOT_DIR)

    # === 📋 Generate HTML report ===
    generate_html_dashboard(plot_dir=OUTPUT_PLOT_DIR)


if __name__ == "__main__":
    main()
