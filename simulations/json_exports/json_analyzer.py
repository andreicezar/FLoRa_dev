#!/usr/bin/env python3
import json
import argparse
from pathlib import Path
from typing import List, Dict, Any
from collections import Counter, defaultdict
from datetime import datetime

# -------------------------
# Utility helpers
# -------------------------
def human_size(n: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1024 or unit == "GB":
            return f"{n:.2f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024.0
    return f"{n:.2f} GB"

def discover_json_files(directory: Path, recursive: bool, pattern: str) -> List[Path]:
    if recursive:
        return sorted(p for p in directory.rglob(pattern) if p.is_file())
    return sorted(p for p in directory.glob(pattern) if p.is_file())

def detect_file_kind(fname: str, obj: Dict[str, Any]) -> str:
    low = fname.lower()
    # filename hints first
    if "app_vectors" in low:
        return "vectors"      # treat app_vectors as vectors kind
    if low.endswith("_vectors.json") or "vectors" in low:
        return "vectors"
    if "scalars" in low:
        return "scalars"
    if "histograms" in low:
        return "histograms"
    if "parameters" in low:
        return "parameters"
    # fallback: inspect data
    if not isinstance(obj, dict) or not obj:
        return "unknown"
    run_key = next(iter(obj.keys()))
    body = obj.get(run_key, {})
    for k in ("vectors", "scalars", "histograms", "parameters"):
        if k in body:
            return k
    return "unknown"

def analyze_file(path: Path) -> Dict[str, Any]:
    """Return lightweight structure stats for a single JSON export."""
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
    except Exception as e:
        sz = path.stat().st_size if path.exists() else 0
        return {"file": path.name, "ok": False, "error": str(e), "size": sz}

    size = path.stat().st_size
    kind = detect_file_kind(path.name, data)

    stats: Dict[str, Any] = {"file": path.name, "ok": True, "kind": kind, "size": size}
    try:
        run_key = next(iter(data.keys()))
        body = data.get(run_key, {})
        stats["has_attributes"] = "attributes" in body
        if kind in ("vectors", "scalars", "histograms", "parameters"):
            items = body.get(kind, [])
            stats["items"] = len(items)
        else:
            stats["items"] = 0
    except Exception:
        stats["items"] = 0
    return stats

# -------------------------
# Scenario grouping
# -------------------------
import re
SCEN_RX = re.compile(
    r'^(?P<base>.+-s\d+)_(?P<kind>(?:app_)?vectors|scalars|histograms|parameters)\.json$',
    re.IGNORECASE
)

def split_scenarios(files: List[Path]):
    """Split matched files into scenarios and collect unmatched."""
    scenarios: Dict[str, List[Path]] = defaultdict(list)
    unmatched: List[str] = []
    for f in files:
        m = SCEN_RX.match(f.name)
        if m:
            scenarios[m.group("base")].append(f)
        else:
            unmatched.append(f.name)
    return scenarios, unmatched

# -------------------------
# Main
# -------------------------
def main():
    ap = argparse.ArgumentParser(description="Analyze OMNeT++ export JSONs; save one combined structure JSON covering all scenarios.")
    ap.add_argument("-d", "--dir", default=None, help="Folder to scan (default: folder containing this script)")
    ap.add_argument("-r", "--recursive", action="store_true", help="Scan subfolders recursively")
    ap.add_argument("-p", "--pattern", default="*.json", help="Glob pattern (default: *.json)")
    ap.add_argument("--list", action="store_true", help="Print a line per file")
    ap.add_argument("-o", "--out", default=None, help="Output JSON path (default: <dir>/all_scenarios_structure.json)")
    args = ap.parse_args()

    base_dir = Path(args.dir).resolve() if args.dir else Path(__file__).resolve().parent
    out_path = Path(args.out).resolve() if args.out else base_dir / "all_scenarios_structure.json"

    files = discover_json_files(base_dir, args.recursive, args.pattern)

    print("🔍 JSON Structure Analyzer")
    print("==================================================")
    print(f"📂 Base: {base_dir}")
    print(f"🔎 Pattern: {args.pattern} | Recursive: {args.recursive}")
    print(f"🗂️  Found: {len(files)} file(s)\n")

    if not files:
        print("Nothing to analyze.")
        # still write an empty template to out_path for reproducibility
        payload = {
            "meta": {
                "base_dir": str(base_dir),
                "pattern": args.pattern,
                "recursive": args.recursive,
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "total_files": 0,
                "total_scenarios": 0,
            },
            "scenarios": {},
            "unmatched": []
        }
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"💾 Wrote: {out_path}")
        return

    scenarios, unmatched = split_scenarios(files)

    per_kind = Counter()
    ok_count = 0
    fail_count = 0
    total_size = 0
    total_items = 0

    # Build per-scenario structure
    scenarios_out: Dict[str, Any] = {}

    for base, flist in sorted(scenarios.items()):
        scen_files_summary = []
        scen_kinds_present = set()
        scen_tot_items = 0
        scen_tot_size = 0

        for f in sorted(flist):
            res = analyze_file(f)
            if res.get("ok"):
                ok_count += 1
                kind = res.get("kind", "unknown")
                per_kind[kind] += 1
                total_items += int(res.get("items", 0))
                scen_tot_items += int(res.get("items", 0))
                scen_kinds_present.add(kind)
            else:
                fail_count += 1

            total_size += res.get("size", 0)
            scen_tot_size += res.get("size", 0)
            scen_files_summary.append(res)

            if args.list:
                if res.get("ok"):
                    print(f"  ✓ {res['file']:60s}  kind={res['kind']:11s}  items={res.get('items',0):6d}  size={human_size(res['size'])}")
                else:
                    print(f"  ✗ {res['file']:60s}  ERROR: {res.get('error','')}")

        expected_kinds = {"vectors", "scalars", "histograms", "parameters"}
        missing = sorted(list(expected_kinds - scen_kinds_present))
        scenarios_out[base] = {
            "files": scen_files_summary,
            "kinds_present": sorted(list(scen_kinds_present)),
            "missing_kinds": missing,
            "totals": {
                "items": scen_tot_items,
                "size_bytes": scen_tot_size,
                "size_human": human_size(scen_tot_size)
            }
        }

    # Also include any JSONs that didn't match the scenario pattern
    unmatched_sorted = sorted(unmatched)

    # Write combined JSON
    payload = {
        "meta": {
            "base_dir": str(base_dir),
            "pattern": args.pattern,
            "recursive": args.recursive,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "total_files": len(files),
            "total_scenarios": len(scenarios_out),
            "unmatched_count": len(unmatched_sorted)
        },
        "summary": {
            "successful_files": ok_count,
            "failed_files": fail_count,
            "total_size_bytes": total_size,
            "total_size_human": human_size(total_size),
            "total_items": total_items,
            "by_type": dict(sorted(per_kind.items()))
        },
        "scenarios": scenarios_out,
        "unmatched": unmatched_sorted
    }

    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("\n📊 SUMMARY")
    print("--------------------------------------------------")
    print(f"Scenarios      : {len(scenarios_out)}")
    print(f"Files analyzed : {len(files)} | Successful: {ok_count} | Failed: {fail_count}")
    print(f"Total size     : {human_size(total_size)}")
    print(f"Total items    : {total_items}")
    if per_kind:
        print("By type:")
        for k in sorted(per_kind.keys()):
            print(f"  - {k:11s}: {per_kind[k]}")
    if unmatched_sorted:
        print(f"\n⚠️  Unmatched (not grouped as scenarios): {len(unmatched_sorted)} file(s)")
    print(f"\n💾 Wrote: {out_path}\n")

if __name__ == "__main__":
    main()
