import json
import csv
import requests
from pathlib import Path

OUT = Path("outputs")
OUT.mkdir(exist_ok=True)

def extract_deims():
    print("Extracting DEIMS fields recursively...")
    path = Path("data/raw/deims_detail/663dac80-211d-4c19-a356-04ee0da0f0eb.json")
    with open(path) as f:
        data = json.load(f)
    fields = set()
    def walk(obj, prefix=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                p = f"{prefix}.{k}" if prefix else k
                if isinstance(v, dict):
                    walk(v, p)
                elif isinstance(v, list) and v and isinstance(v[0], dict):
                    walk(v[0], p + "[0]")
                else:
                    fields.add(p)
    if "attributes" in data:
        walk(data["attributes"])
    return [{"ri": "DEIMS", "field": f, "definition": ""} for f in sorted(fields)]

def extract_icos_cached():
    print("Extracting ICOS cached fields...")
    path = Path("data/raw/icos_stations_page_0001.json")
    with open(path) as f:
        data = json.load(f)
    bindings = data.get("results", {}).get("bindings", [])
    if not bindings: return []
    return [{"ri": "ICOS_cached", "field": k, "definition": ""} for k in sorted(bindings[0].keys())]

def extract_icos_live():
    print("Fetching ICOS live schema via SPARQL...")
    query = """
    SELECT DISTINCT ?p WHERE {
      <http://meta.icos-cp.eu/resources/stations/AS_ARN> ?p ?o .
    }
    """
    try:
        resp = requests.get("https://meta.icos-cp.eu/sparql", params={"query": query, "format": "application/sparql-results+json"}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        fields = set()
        for b in data["results"]["bindings"]:
            fields.add(b["p"]["value"])
        return [{"ri": "ICOS_live", "field": f, "definition": ""} for f in sorted(fields)]
    except Exception as e:
        print(f"  ERROR ICOS live: {e}")
        return []

def extract_actris():
    print("Extracting ACTRIS fields...")
    path = Path("data/raw/actris_facilities.json")
    with open(path) as f:
        data = json.load(f)
    record = data[0] if isinstance(data, list) and data else data
    fields = set()
    for k, v in record.items():
        fields.add(k)
        if isinstance(v, dict):
            for sub_k in v.keys():
                fields.add(f"{k}.{sub_k}")
    return [{"ri": "ACTRIS", "field": f, "definition": ""} for f in sorted(fields)]

def main():
    all_fields = []
    all_fields.extend(extract_deims())
    all_fields.extend(extract_icos_cached())
    all_fields.extend(extract_icos_live())
    all_fields.extend(extract_actris())

    out = OUT / "all_schema_fields.csv"
    with open(out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["ri", "field", "definition"])
        writer.writeheader()
        writer.writerows(all_fields)
    print(f"Saved {len(all_fields)} fields to {out}")

if __name__ == "__main__":
    main()
