import json
import csv
from pathlib import Path

OUT = Path("outputs")
OUT.mkdir(exist_ok=True)

def extract_deims():
    path = Path("data/raw/deims_detail/663dac80-211d-4c19-a356-04ee0da0f0eb.json")
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, list): data = data[0]
    fields = []
    for k, v in data.items():
        fields.append({"ri": "DEIMS", "field_path": k, "example_value": str(v)[:100]})
    return fields

def extract_icos():
    path = Path("data/raw/icos_stations_page_0001.json")
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, list) and data:
        record = data[0]
    elif isinstance(data, dict) and "stations" in data:
        record = data["stations"][0]
    else:
        record = data
    fields = []
    for k, v in record.items():
        fields.append({"ri": "ICOS", "field_path": k, "example_value": str(v)[:100]})
    return fields

def extract_actris():
    path = Path("data/raw/actris_facilities.json")
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, list) and data:
        record = data[0]
    elif isinstance(data, dict):
        record = data
    else:
        record = {}
    fields = []
    for k, v in record.items():
        fields.append({"ri": "ACTRIS", "field_path": k, "example_value": str(v)[:100]})
    return fields

def main():
    all_fields = []
    for name, fn in [("DEIMS", extract_deims), ("ICOS", extract_icos), ("ACTRIS", extract_actris)]:
        try:
            print(f"Extracting {name}...")
            fields = fn()
            all_fields.extend(fields)
            print(f"  {len(fields)} fields found.")
        except Exception as e:
            print(f"  ERROR {name}: {e}")
    
    out_file = OUT / "extracted_schemas.csv"
    with open(out_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["ri", "field_path", "example_value"])
        writer.writeheader()
        writer.writerows(all_fields)
    print(f"Saved {len(all_fields)} rows to {out_file}")

if __name__ == "__main__":
    main()
