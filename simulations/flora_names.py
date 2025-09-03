#!/usr/bin/env python3
"""
List every variable/metric name (parameters, scalars, histograms, vectors)
from OMNeT++/FLoRa JSON exports.

- Scans a directory for *.json files.
- Classifies files into: parameters / scalars / histograms / vectors
  based on filename substrings (case-insensitive).
- Extracts the "name" field from each entry in the corresponding list.
- Works whether the JSON has the list at top-level or nested under run IDs.
- Prints a compact summary and saves all unique names to a JSON file.

Usage:
  python list_flora_metric_names.py --json-dir json_exports
  python list_flora_metric_names.py --json-dir json_exports --filter scenario-02
  python list_flora_metric_names.py --json-dir json_exports --out flora_names.json

Tip (Windows PowerShell): avoid emojis in prints; this script uses plain ASCII.
"""

from pathlib import Path
from typing import Dict, Any, List, Optional, Set
import argparse, json, sys

# ----------------------------- IO helpers ------------------------------------
def read_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def get_items(json_obj: Any, key: str) -> List[dict]:
    """
    Return a combined list for `key` ("parameters", "scalars", "histograms", "vectors")
    handling both shapes:
      - {"scalars": [...]}  (top-level)
      - {"run1": {"scalars":[...]}, "run2": {...}} (runs grouped)
    If multiple runs exist, they are concatenated.
    """
    out: List[dict] = []
    if isinstance(json_obj, dict):
        if key in json_obj and isinstance(json_obj[key], list):
            return list(json_obj[key])
        # gather from nested run blocks
        for v in json_obj.values():
            if isinstance(v, dict) and key in v and isinstance(v[key], list):
                out.extend(v[key])
    return out

# --------------------------- file classification ------------------------------
def classify_json_file(p: Path) -> Optional[str]:
    """
    Return one of: "parameters" | "scalars" | "histograms" | "vectors"
    or None if not recognized. Uses filename substring.
    """
    name = p.name.lower()
    if "parameters" in name:
        return "parameters"
    if "scalars" in name:
        return "scalars"
    if "histograms" in name:
        return "histograms"
    # treat both "...app_vectors..." and generic "...vectors..." as vectors
    if "app_vectors" in name or "vectors" in name:
        return "vectors"
    return None

# ------------------------------ main logic -----------------------------------
def main():
    ap = argparse.ArgumentParser(description="Extract all metric/variable names from FLoRa JSON exports")
    ap.add_argument("--json-dir", type=Path, default=Path("json_exports"),
                    help="Directory containing JSON export files")
    ap.add_argument("--filter", type=str, default="",
                    help="Only include files whose name contains this substring (e.g., 'scenario-02')")
    ap.add_argument("--out", type=Path, default=Path("flora_names.json"),
                    help="Where to save the names index (JSON)")
    args = ap.parse_args()

    if not args.json_dir.exists():
        print(f"JSON directory not found: {args.json_dir}")
        sys.exit(1)

    filt = (args.filter or "").lower().strip()

    files = sorted([p for p in args.json_dir.glob("*.json")
                    if not filt or filt in p.name.lower()])

    if not files:
        print("No JSON files matched.")
        sys.exit(0)

    grouped: Dict[str, List[Path]] = {"parameters": [], "scalars": [], "histograms": [], "vectors": []}
    for p in files:
        kind = classify_json_file(p)
        if kind:
            grouped[kind].append(p)

    # Containers for unique names and simple frequency (how many files they appeared in)
    names: Dict[str, Set[str]] = {k: set() for k in grouped.keys()}
    file_counts: Dict[str, Dict[str, int]] = {k: {} for k in grouped.keys()}

    # Extract name fields
    for kind, flist in grouped.items():
        for fp in flist:
            try:
                obj = read_json(fp)
            except Exception as e:
                print(f"[warn] Could not read {fp.name}: {e}")
                continue

            items = get_items(obj, "parameters" if kind == "parameters" else kind)
            # Some exports use "statistics" instead of "histograms"
            if not items and kind == "histograms":
                items = get_items(obj, "statistics")

            seen_this_file: Set[str] = set()
            for it in items:
                if not isinstance(it, dict):
                    continue
                nm = it.get("name")
                if not isinstance(nm, str) or not nm:
                    continue
                names[kind].add(nm)
                seen_this_file.add(nm)
            # track in how many files this name appeared (per kind)
            for nm in seen_this_file:
                file_counts[kind][nm] = file_counts[kind].get(nm, 0) + 1

    # Print summary
    total_files = sum(len(v) for v in grouped.values())
    print("============================================================")
    print("FLoRa Metric/Variable Name Extraction")
    print("============================================================")
    print(f"Folder      : {args.json_dir}")
    if filt:
        print(f"Filter      : '{filt}'")
    print(f"Files found : {total_files} (parameters={len(grouped['parameters'])},"
          f" scalars={len(grouped['scalars'])}, histograms={len(grouped['histograms'])},"
          f" vectors={len(grouped['vectors'])})")
    print()
    for kind in ("parameters", "scalars", "histograms", "vectors"):
        print(f"{kind.capitalize():<11}: {len(names[kind])} unique names")

    # Save JSON index
    out_obj: Dict[str, Any] = {
        "summary": {
            "json_dir": str(args.json_dir),
            "filter": filt or None,
            "files": {k: [str(p.name) for p in v] for k, v in grouped.items()},
            "counts": {k: len(names[k]) for k in names.keys()},
        },
        "names": {k: sorted(list(v)) for k, v in names.items()},
        "file_frequency": {k: dict(sorted(v.items(), key=lambda x: (-x[1], x[0])))
                           for k, v in file_counts.items()},
    }
    try:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(out_obj, f, ensure_ascii=False, indent=2)
        print(f"\nSaved names index to: {args.out}")
    except Exception as e:
        print(f"[warn] Could not write {args.out}: {e}")

    # Optional: print a small sample of each group to console
    def sample(lst: List[str], n=10) -> List[str]:
        return lst[:n] if len(lst) <= n else lst[:n] + ["..."]

    print("\nExamples:")
    for kind in ("parameters", "scalars", "histograms", "vectors"):
        ex = sample(sorted(names[kind]))
        if ex:
            print(f"- {kind}: {', '.join(ex)}")
        else:
            print(f"- {kind}: (none)")

if __name__ == "__main__":
    main()
