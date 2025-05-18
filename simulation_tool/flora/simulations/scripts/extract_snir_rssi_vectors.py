
import json

def extract_signal_vector_ids(vectors, signal_keyword):
    """
    Extracts signal vector IDs based on keyword match in the vector name.
    Assigns index as node ID assuming order is preserved.
    """
    matching_vectors = [
        (idx, vec)
        for idx, vec in enumerate(vectors)
        if signal_keyword in vec.get("name", "").lower()
    ]
    return {i: idx for i, (idx, _) in enumerate(matching_vectors)}

# Load the JSON file (assumed to be in same directory)
with open("../export_json/DER_4GW-s-10ed_app.json", "r") as f:
    data = json.load(f)

# Adjust this key if needed — automatically pick the first top-level key
main_key = next(iter(data))
vectors = data[main_key].get("vectors", [])

# Extract SNIR and RSSI vectors
snir_vector_ids = extract_signal_vector_ids(vectors, "snir")
rssi_vector_ids = extract_signal_vector_ids(vectors, "rssi")

print("SNIR vector IDs per node:")
for node_id in sorted(snir_vector_ids):
    print(f"  Node {node_id}: vector ID {snir_vector_ids[node_id]}")

print("\nRSSI vector IDs per node:")
for node_id in sorted(rssi_vector_ids):
    print(f"  Node {node_id}: vector ID {rssi_vector_ids[node_id]}")
