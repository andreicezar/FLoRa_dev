import tkinter as tk
from tkinter import filedialog, messagebox
import matplotlib.pyplot as plt

# Exemplu cu date introduse manual
data_per_scenario = {
    "1ED_Rayleigh": {"DER": [0.06], "SF": [7], "TP": [14]},
    "10ED_Rayleigh": {"DER": [0.09, 0.85, 0.60, 0.81, 0.87, 0.41, 0.11, 0.18, 0.90, 0.05], 
                      "SF": [7,8,7,8,7,8,7,7,10,7], 
                      "TP": [14,2,14,2,14,2,14,14,2,14]},
    "10ED_noRayleigh": {"DER": [0.09, 0.85, 0.60, 0.81, 0.87, 0.41, 0.11, 0.18, 0.90, 0.05], 
                        "SF": [7,8,7,8,7,8,7,7,10,7], 
                        "TP": [14,2,14,2,14,2,14,14,2,14]},
}

class BoxPlotGUI:
    def __init__(self, root, data_per_scenario):
        self.root = root
        self.data = data_per_scenario
        self.metrics = ["DER", "SF", "TP"]

        self.root.title("LoRaWAN Boxplot GUI")
        self.label = tk.Label(root, text="Selectează metrică pentru boxplot:")
        self.label.pack(pady=5)

        self.metric_var = tk.StringVar(value="DER")
        self.menu = tk.OptionMenu(root, self.metric_var, *self.metrics)
        self.menu.pack(pady=5)

        self.plot_button = tk.Button(root, text="Plotează boxplot", command=self.plot_boxplot)
        self.plot_button.pack(pady=20)

    def plot_boxplot(self):
        metric = self.metric_var.get()
        data = [self.data[sc][metric] for sc in self.data]
        labels = list(self.data.keys())
        plt.figure(figsize=(8,5))
        plt.boxplot(data, labels=labels)
        plt.ylabel(metric + " per Node")
        plt.title(f"{metric} distribution per scenario")
        plt.grid(axis="y")
        plt.show()

if __name__ == "__main__":
    root = tk.Tk()
    gui = BoxPlotGUI(root, data_per_scenario)
    root.mainloop()
