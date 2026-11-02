import json
import csv
from pathlib import Path

OUT = Path("outputs")
OUT.mkdir(exist_ok=True)

def extract_deims():
    path = Path("data/raw/deims_detail/663dac80-211d-4c19-a356-04ee0da0f0eb.json")
    with open(path) as f:
        data = json.load(f)
    fields = []
    for k, v in data.items():
        if k == "attributes" and isinstance(v, dict):
            for sub_k, sub_v in v.items():
                fields.append({"ri": "DEIMS", "field_path": sub_k, "example_value": str(sub_v)[:100]})
        elif k not in ("id", "created", "changed"):
            fields.append({"ri": "DEIMS", "field_path": k, "example_value": str(v)[:100]})
    return fields

def extract_icos():
    path = Path("data/raw/icos_stations_page_0001.json")
    with open(path) as f:
        data = json.load(f)
    fields = []
    bindings = data.get("results", {}).get("bindings", [])
    if bindings:
        for k in bindings[0].keys():
            fields.append({"ri": "ICOS", "field_path": k, "example_value": ""})
    return fields

def extract_actris():
    path = Path("data/raw/actris_facilities.json")
    with open(path) as f:
        data = json.load(f)
    record = data[0] if isinstance(data, list) and data else data
    fields = []
    for k, v in record.items():
        if isinstance(v, dict) and k in ("location", "extra_metadata"):
            for sub_k, sub_v in v.items():
                fields.append({"ri": "ACTRIS", "field_path": f"{k}.{sub_k}", "example_value": str(sub_v)[:100]})
        else:
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
