
import os


def generate_html_dashboard(plot_dir="plots", output_file="analysis_dashboard.html"):
    html = ['''
    <html>
    <head>
        <meta charset="UTF-8">
        <title>LoRaWAN Scenario Analysis</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                margin: 20px;
            }
            h1 {
                color: #333;
            }
            pre {
                background: #f9f9f9;
                border: 1px solid #ccc;
                padding: 10px;
                overflow: auto;
            }
            .scenario-container {
                display: flex;
                gap: 20px;
                align-items: flex-start;
                margin-bottom: 40px;
            }
            .left-panel {
                width: 48%;
                max-height: 800px;
                overflow: auto;
                padding-right: 2%;
            }
            .right-panel {
                width: 50%;
                max-height: 800px;
                overflow-y: auto;
                overflow-x: visible;
                border-left: 1px solid #ddd;
                padding-left: 10px;
                position: relative;
            }
            .image-block {
                display: flex;
                flex-direction: column;
                align-items: flex-start;
                margin-bottom: 20px;
            }
            .image-label {
                font-family: monospace;
                font-size: 14px;
                margin-bottom: 5px;
            }
            .image-container {
                border: 1px solid #ddd;
                padding: 5px;
                position: relative;
                overflow: hidden;
                width: 550px;
                height: 375px;
            }
            .zoomable {
                width: 100%;
                height: 100%;
                object-fit: contain;
                transform-origin: 0 0;
                position: relative;
                cursor: grab;
            }
            .zoomable:active {
                cursor: grabbing;
            }
            .reset-btn {
                margin-top: 5px;
                padding: 3px 10px;
                font-size: 12px;
                cursor: pointer;
            }
        </style>
    </head>
    <body>
    ''']

    html.append('<h1>📊 LoRaWAN Simulation Dashboard</h1>')

    for scenario in sorted(os.listdir(plot_dir)):
        scenario_path = os.path.join(plot_dir, scenario)
        if not os.path.isdir(scenario_path):
            continue

        html.append(f'<h2>📁 Scenario: {scenario}</h2>')
        html.append('<div class="scenario-container">')

        report_path = os.path.join(scenario_path, "report.txt")
        report_html = "<pre style='font-size:13px; line-height:1.3;'>"
        if os.path.isfile(report_path):
            with open(report_path, "r", encoding="utf-8") as rfile:
                report_html += rfile.read()
        else:
            report_html += "⚠️ Report not found."
        report_html += "</pre>"
        html.append(f'<div class="left-panel">{report_html}</div>')

        html.append('<div class="right-panel">')

        for file in sorted(os.listdir(scenario_path)):
            if not file.lower().endswith((".png", ".jpeg", ".jpg")):
                continue

            img_path = os.path.abspath(os.path.join(plot_dir, scenario, file)).replace("\\\\", "/")
            html.append(f'''
                <div class="image-block">
                    <div class="image-label"><b>{file}</b></div>
                    <div class="image-container">
                        <img src="file://{img_path}" class="zoomable">
                    </div>
                    <button class="reset-btn" onclick="resetZoom(this)">🔄 Reset Zoom</button>
                </div>
            ''')

        html.append('</div></div><hr>')
    # === GLOBAL SUMMARY SECTION ===
    html.append('<h2>📈 Summary Plots Across All Scenarios</h2>')
    summary_images = [
        f for f in sorted(os.listdir(plot_dir))
        if f.lower().endswith((".png", ".jpg", ".jpeg")) and os.path.isfile(os.path.join(plot_dir, f))
    ]

    html.append('<div class="right-panel">')
    for img_name in summary_images:
        img_path = os.path.abspath(os.path.join(plot_dir, img_name)).replace("\\", "/")
        if os.path.isfile(os.path.join(plot_dir, img_name)):
            html.append(f'''
                <div class="image-block">
                    <div class="image-label"><b>{img_name}</b></div>
                    <div class="image-container">
                        <img src="file://{img_path}" class="zoomable">
                    </div>
                    <button class="reset-btn" onclick="resetZoom(this)">🔄 Reset Zoom</button>
                </div>
            ''')
    html.append('</div><hr>')
    html.append('''
    <script>
        function enablePanZoom(img) {
            let scale = 1, tx = 0, ty = 0;
            let isDragging = false, lastX = 0, lastY = 0;
            img.style.transform = "translate(0px, 0px) scale(1)";
            img.dataset.transform = img.style.transform;

            img.addEventListener('wheel', (e) => {
                e.preventDefault();
                const delta = e.deltaY < 0 ? 1.1 : 0.9;
                const rect = img.getBoundingClientRect();
                const offsetX = e.clientX - rect.left;
                const offsetY = e.clientY - rect.top;

                const newScale = scale * delta;
                const dx = offsetX * (1 - delta);
                const dy = offsetY * (1 - delta);

                tx += dx;
                ty += dy;
                scale = newScale;

                img.style.transform = `translate(${tx}px, ${ty}px) scale(${scale})`;
                img.dataset.transform = img.style.transform;
            });

            img.addEventListener('mousedown', (e) => {
                isDragging = true;
                lastX = e.clientX;
                lastY = e.clientY;
            });

            window.addEventListener('mouseup', () => isDragging = false);
            window.addEventListener('mousemove', (e) => {
                if (!isDragging) return;
                const dx = e.clientX - lastX;
                const dy = e.clientY - lastY;
                lastX = e.clientX;
                lastY = e.clientY;
                tx += dx;
                ty += dy;
                img.style.transform = `translate(${tx}px, ${ty}px) scale(${scale})`;
                img.dataset.transform = img.style.transform;
            });
        }

        function resetZoom(btn) {
            const img = btn.parentElement.querySelector('.zoomable');
            img.style.transform = "translate(0px, 0px) scale(1)";
            img.dataset.transform = img.style.transform;
        }

        document.addEventListener('DOMContentLoaded', () => {
            document.querySelectorAll('.zoomable').forEach(enablePanZoom);
        });
    </script>
    </body></html>
    ''')
    # Save the HTML file
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(html))

    print(f"✅ Dashboard with smaller zoomable images saved to: {output_file}")
