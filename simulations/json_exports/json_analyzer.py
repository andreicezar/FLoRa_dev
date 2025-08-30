import json
import os
from typing import Any, Dict, List, Set
from collections import defaultdict, Counter

class JSONStructureAnalyzer:
    def __init__(self):
        self.structures = {}
    
    def get_type_info(self, value: Any) -> str:
        """Get detailed type information for a value."""
        if value is None:
            return "null"
        elif isinstance(value, bool):
            return "boolean"
        elif isinstance(value, int):
            return "integer"
        elif isinstance(value, float):
            return "float"
        elif isinstance(value, str):
            return "string"
        elif isinstance(value, list):
            if len(value) == 0:
                return "array (empty)"
            # Check types of array elements
            element_types = set()
            for item in value[:10]:  # Sample first 10 items
                element_types.add(self.get_type_info(item))
            if len(element_types) == 1:
                return f"array of {list(element_types)[0]} (length: {len(value)})"
            else:
                return f"array of mixed types {sorted(element_types)} (length: {len(value)})"
        elif isinstance(value, dict):
            return f"object ({len(value)} keys)"
        else:
            return f"unknown ({type(value).__name__})"
    
    def analyze_object_structure(self, obj: Dict[str, Any], path: str = "root") -> Dict[str, Any]:
        """Recursively analyze the structure of a JSON object."""
        structure = {
            "type": "object",
            "keys": {},
            "key_count": len(obj),
            "path": path
        }
        
        for key, value in obj.items():
            current_path = f"{path}.{key}"
            
            if isinstance(value, dict):
                structure["keys"][key] = self.analyze_object_structure(value, current_path)
            elif isinstance(value, list):
                structure["keys"][key] = self.analyze_array_structure(value, current_path)
            else:
                structure["keys"][key] = {
                    "type": self.get_type_info(value),
                    "path": current_path,
                    "sample_value": str(value)[:100] + "..." if len(str(value)) > 100 else str(value)
                }
        
        return structure
    
    def analyze_array_structure(self, arr: List[Any], path: str = "root") -> Dict[str, Any]:
        """Analyze the structure of a JSON array."""
        structure = {
            "type": "array",
            "length": len(arr),
            "path": path,
            "element_types": Counter(),
            "sample_elements": []
        }
        
        # Analyze element types
        for i, item in enumerate(arr[:20]):  # Sample first 20 items
            item_type = self.get_type_info(item)
            structure["element_types"][item_type] += 1
            
            if i < 3:  # Store first 3 as samples
                if isinstance(item, dict):
                    structure["sample_elements"].append(self.analyze_object_structure(item, f"{path}[{i}]"))
                elif isinstance(item, list):
                    structure["sample_elements"].append(self.analyze_array_structure(item, f"{path}[{i}]"))
                else:
                    structure["sample_elements"].append({
                        "type": item_type,
                        "value": str(item)[:100] + "..." if len(str(item)) > 100 else str(item)
                    })
        
        return structure
    
    def analyze_json_file(self, filepath: str) -> Dict[str, Any]:
        """Analyze a single JSON file and return its structure."""
        try:
            print(f"Analyzing {filepath}...")
            
            with open(filepath, 'r', encoding='utf-8') as file:
                data = json.load(file)
            
            file_info = {
                "filename": os.path.basename(filepath),
                "file_size": os.path.getsize(filepath),
                "root_type": self.get_type_info(data)
            }
            
            if isinstance(data, dict):
                file_info["structure"] = self.analyze_object_structure(data)
            elif isinstance(data, list):
                file_info["structure"] = self.analyze_array_structure(data)
            else:
                file_info["structure"] = {
                    "type": self.get_type_info(data),
                    "value": str(data)[:200] + "..." if len(str(data)) > 200 else str(data)
                }
            
            return file_info
            
        except json.JSONDecodeError as e:
            return {
                "filename": os.path.basename(filepath),
                "error": f"JSON decode error: {str(e)}",
                "file_size": os.path.getsize(filepath) if os.path.exists(filepath) else 0
            }
        except Exception as e:
            return {
                "filename": os.path.basename(filepath),
                "error": f"Error reading file: {str(e)}",
                "file_size": os.path.getsize(filepath) if os.path.exists(filepath) else 0
            }
    
    def print_structure(self, structure: Dict[str, Any], indent: int = 0) -> None:
        """Pretty print the JSON structure."""
        prefix = "  " * indent
        
        if "error" in structure:
            print(f"{prefix}❌ {structure['filename']}: {structure['error']}")
            return
        
        print(f"{prefix}📁 {structure['filename']} ({structure['file_size']:,} bytes)")
        print(f"{prefix}   Root type: {structure['root_type']}")
        
        self._print_structure_recursive(structure["structure"], indent + 1)
        print()
    
    def _print_structure_recursive(self, structure: Dict[str, Any], indent: int) -> None:
        """Recursively print structure details."""
        prefix = "  " * indent
        
        if structure["type"] == "object":
            print(f"{prefix}📦 Object with {structure['key_count']} keys:")
            for key, value in structure["keys"].items():
                print(f"{prefix}  🔑 {key}:")
                if isinstance(value, dict) and "type" in value:
                    if value["type"] in ["object", "array"]:
                        self._print_structure_recursive(value, indent + 2)
                    else:
                        print(f"{prefix}    {value['type']}")
                        if "sample_value" in value:
                            print(f"{prefix}    Sample: {value['sample_value']}")
        
        elif structure["type"] == "array":
            print(f"{prefix}📋 Array with {structure['length']} elements:")
            print(f"{prefix}  Element types: {dict(structure['element_types'])}")
            
            if structure["sample_elements"]:
                print(f"{prefix}  Sample elements:")
                for i, sample in enumerate(structure["sample_elements"][:2]):
                    print(f"{prefix}    [{i}]:")
                    if isinstance(sample, dict) and "type" in sample:
                        if sample["type"] in ["object", "array"]:
                            self._print_structure_recursive(sample, indent + 3)
                        else:
                            print(f"{prefix}      {sample.get('type', 'unknown')}: {sample.get('value', '')}")

    def analyze_files(self, file_paths: List[str]) -> None:
        """Analyze multiple JSON files and display their structures."""
        print("🔍 JSON Structure Analyzer")
        print("=" * 50)
        
        results = []
        for filepath in file_paths:
            if not os.path.exists(filepath):
                print(f"⚠️  File not found: {filepath}")
                continue
                
            result = self.analyze_json_file(filepath)
            results.append(result)
            self.structures[filepath] = result
        
        print("\n📊 STRUCTURE ANALYSIS RESULTS")
        print("=" * 50)
        
        for result in results:
            self.print_structure(result)
        
        # Summary
        print("📈 SUMMARY")
        print("-" * 30)
        total_size = sum(r.get("file_size", 0) for r in results)
        successful = len([r for r in results if "error" not in r])
        failed = len([r for r in results if "error" in r])
        
        print(f"Files analyzed: {len(results)}")
        print(f"Successful: {successful}")
        print(f"Failed: {failed}")
        print(f"Total size: {total_size:,} bytes ({total_size/1024/1024:.2f} MB)")

def main():
    # Define your JSON file paths here
    json_files = [
        "scenario-01-baseline-08_adr_no_init-s0_app_vectors.json",
        "scenario-01-baseline-08_adr_no_init-s0_histograms.json", 
        "scenario-01-baseline-08_adr_no_init-s0_parameters.json",
        "scenario-01-baseline-08_adr_no_init-s0_scalars.json"
    ]
    
    # Alternative: automatically find all JSON files in current directory
    # json_files = [f for f in os.listdir(".") if f.endswith(".json")]
    
    analyzer = JSONStructureAnalyzer()
    analyzer.analyze_files(json_files)
    
    # Optional: Save results to a file
    # with open("json_structure_analysis.json", "w") as f:
    #     json.dump(analyzer.structures, f, indent=2, default=str)
    #     print("Results saved to json_structure_analysis.json")

if __name__ == "__main__":
    main()