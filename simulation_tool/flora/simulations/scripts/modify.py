import os
import re

folder = r"../config_files_for_scenarios/payload_20_diff_eds_tests"  # Update as needed

def extract_num_eds(filename):
    m = re.search(r'8GW(\d+)ED', filename, re.IGNORECASE)
    return int(m.group(1)) if m else None

def update_line(line, num_eds):
    # Output file name pattern
    vec_pattern = r'^output-vector-file\s*='
    sca_pattern = r'^output-scalar-file\s*='
    outdir = "../../results_and_analysis/scenario_4/results_payload_20/"
    base = f"8GW-s-{num_eds}ed_ADRopt_20B_Rayleigh"
    if re.match(vec_pattern, line):
        return f'output-vector-file = {outdir}{base}.ini.vec\n'
    if re.match(sca_pattern, line):
        return f'output-scalar-file = {outdir}{base}.ini.sca\n'
    # Update dataSize for any node
    line = re.sub(r'(\*\*\.loRaNodes\[\*?\d*\]\.app\[0\]\.dataSize\s*=\s*)15B', r'\g<1>20B', line)
    # Update numberOfNodes
    if line.strip().startswith("**.numberOfNodes"):
        return f"**.numberOfNodes = {num_eds}\n"
    # Use regex to fix ALL variants of constraint area (spaces/decimals)
    line = re.sub(r'\*\*\.constraintAreaMinX\s*=.*', '**.constraintAreaMinX = -20000m', line)
    line = re.sub(r'\*\*\.constraintAreaMinY\s*=.*', '**.constraintAreaMinY = -20000m', line)
    line = re.sub(r'\*\*\.constraintAreaMaxX\s*=.*', '**.constraintAreaMaxX = 20000m', line)
    line = re.sub(r'\*\*\.constraintAreaMaxY\s*=.*', '**.constraintAreaMaxY = 20000m', line)
    # Set *.debug = false (replaces any existing)
    if line.strip().startswith("*.debug"):
        return "*.debug = false\n"
    # Remove any old *.networkServer.debugADR lines (will be re-inserted)
    if line.strip().startswith("*.networkServer.debugADR"):
        return ''
    return line

def process_and_insert_debug(lines):
    # Ensure *.debug = false at the top and insert *.networkServer.debugADR = false right after
    new_lines = []
    debug_set = False
    adr_inserted = False
    for line in lines:
        if line.strip().startswith("*.debug") and not debug_set:
            new_lines.append("*.debug = false\n")
            new_lines.append("*.networkServer.debugADR = false\n")
            debug_set = True
            adr_inserted = True
        elif line.strip().startswith("*.networkServer.debugADR"):
            # Skip any stray lines, handled above
            continue
        else:
            new_lines.append(line)
    # If *.debug was not present, insert at the very top
    if not debug_set:
        new_lines.insert(0, "*.networkServer.debugADR = false\n")
        new_lines.insert(0, "*.debug = false\n")
    return new_lines

def add_missing_lines(lines):
    # Constraint area
    has_minx = any("**.constraintAreaMinX" in l for l in lines)
    has_miny = any("**.constraintAreaMinY" in l for l in lines)
    has_maxx = any("**.constraintAreaMaxX" in l for l in lines)
    has_maxy = any("**.constraintAreaMaxY" in l for l in lines)
    if not has_minx:
        lines.append("**.constraintAreaMinX = -2500\n")
    if not has_miny:
        lines.append("**.constraintAreaMinY = -2500\n")
    if not has_maxx:
        lines.append("**.constraintAreaMaxX = 2500\n")
    if not has_maxy:
        lines.append("**.constraintAreaMaxY = 2500\n")
    return lines

for filename in os.listdir(folder):
    if filename.endswith(".ini") and "8GW" in filename and "ED" in filename:
        num_eds = extract_num_eds(filename)
        if num_eds is None:
            print(f"Skipped {filename}: could not find ED count.")
            continue
        ini_path = os.path.join(folder, filename)
        with open(ini_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        # Apply main updates
        new_lines = [update_line(line, num_eds) for line in lines]
        # Ensure *.debug and *.networkServer.debugADR at top
        new_lines = process_and_insert_debug(new_lines)
        # Add any missing constraint area lines
        new_lines = add_missing_lines(new_lines)
        with open(ini_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        print(f"Updated: {filename} (numberOfNodes = {num_eds})")

print("All .ini files updated with debug, debugADR, area, naming, and all requested settings!")