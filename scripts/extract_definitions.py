import json
import csv
from pathlib import Path

OUT = Path("outputs")
OUT.mkdir(exist_ok=True)

def fetch_deims():
    print("Extracting DEIMS fields from all cached site JSONs...")
    path = Path("data/raw/deims_detail")
    keys = set()
    for filepath in path.glob("*.json"):
        with open(filepath) as f:
            data = json.load(f)
            for k, v in data.items():
                if k == "attributes" and isinstance(v, dict):
                    keys.update(v.keys())
                elif k not in ("id", "created", "changed", "type"):
                    keys.add(k)
    results = [{"ri": "DEIMS", "field": k, "label": k, "definition": "", "flagged": "yes"} for k in sorted(keys)]
    print(f"  Found {len(results)} unique DEIMS fields.")
    return results

def fetch_icos():
    print("Extracting ICOS fields from cached station JSONs...")
    keys = set()
    for page in ["0001", "0002"]:
        path = Path(f"data/raw/icos_stations_page_{page}.json")
        if path.exists():
            with open(path) as f:
                data = json.load(f)
                bindings = data.get("results", {}).get("bindings", [])
                for b in bindings:
                    keys.update(b.keys())
    results = [{"ri": "ICOS", "field": k, "label": k, "definition": "", "flagged": "yes"} for k in sorted(keys)]
    print(f"  Found {len(results)} unique ICOS fields.")
    return results

def fetch_actris():
    print("Extracting ACTRIS fields from cached facilities JSON...")
    path = Path("data/raw/actris_facilities.json")
    with open(path) as f:
        data = json.load(f)
    keys = set()
    records = data if isinstance(data, list) else [data]
    for record in records:
        for k, v in record.items():
            keys.add(k)
            if isinstance(v, dict) and k in ("location", "extra_metadata"):
                for sub_k in v.keys():
                    keys.add(f"{k}.{sub_k}")
    results = [{"ri": "ACTRIS", "field": k, "label": k, "definition": "", "flagged": "yes"} for k in sorted(keys)]
    print(f"  Found {len(results)} unique ACTRIS fields.")
    return results

def main():
    all_results = []
    all_results.extend(fetch_deims())
    all_results.extend(fetch_icos())
    all_results.extend(fetch_actris())

    out_file = OUT / "field_definitions.csv"
    with open(out_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["ri", "field", "label", "definition", "flagged"])
        writer.writeheader()
        writer.writerows(all_results)
    print(f"Saved {len(all_results)} rows to {out_file}")

if __name__ == "__main__":
    main()
