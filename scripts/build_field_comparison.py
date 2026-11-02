import json
import csv
import requests
from pathlib import Path

OUT = Path("outputs")
OUT.mkdir(exist_ok=True)

def build_deims():
    print("Building DEIMS fields (filtering contact info)...")
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
    
    # SAFETY RULE: Filter out contact fields (names, emails)
    clean_fields = [f for f in fields if not f.startswith("contact.")]
    
    # DEIMS does not expose a public schema definition endpoint in the same way
    return [{"ri": "DEIMS", "field": f, "definition": "FLAGGED: No published API definition found"} for f in sorted(clean_fields)]

def build_icos():
    print("Building ICOS fields and definitions from SPARQL...")
    query = """
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
    SELECT DISTINCT ?p ?label ?comment WHERE {
      <http://meta.icos-cp.eu/resources/stations/AS_ARN> ?p ?o .
      OPTIONAL { ?p rdfs:label ?label }
      OPTIONAL { ?p rdfs:comment ?comment }
      OPTIONAL { ?p skos:definition ?comment }
    }
    """
    try:
        resp = requests.get("https://meta.icos-cp.eu/sparql", params={"query": query, "format": "application/sparql-results+json"}, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        results = []
        for b in data["results"]["bindings"]:
            p = b["p"]["value"].split("/")[-1] # get the short property name
            comment = b.get("comment", {}).get("value", "")
            defn = comment if comment else "FLAGGED: No published API definition found"
            results.append({"ri": "ICOS", "field": p, "definition": defn})
        # Remove duplicates if the SPARQL query returns multiple labels/comments
        seen = set()
        unique = []
        for r in results:
            if r["field"] not in seen:
                seen.add(r["field"])
                unique.append(r)
        return sorted(unique, key=lambda x: x["field"])
    except Exception as e:
        print(f"  ERROR ICOS: {e}")
        return []

def build_actris():
    print("Building ACTRIS fields and definitions from OpenAPI spec...")
    try:
        resp = requests.get("https://prod-actris-md.nilu.no/v3/api-docs", timeout=30)
        resp.raise_for_status()
        data = resp.json()
        schemas = data.get("components", {}).get("schemas", {})
        facility = schemas.get("Facility", {})
        properties = facility.get("properties", {})
        
        results = []
        for prop, details in properties.items():
            desc = details.get("description", "")
            defn = desc if desc else "FLAGGED: No published API definition found"
            results.append({"ri": "ACTRIS", "field": prop, "definition": defn})
        return sorted(results, key=lambda x: x["field"])
    except Exception as e:
        print(f"  ERROR ACTRIS: {e}")
        return []

def main():
    all_fields = []
    all_fields.extend(build_deims())
    all_fields.extend(build_icos())
    all_fields.extend(build_actris())

    out_file = OUT / "field_comparison_dataset.csv"
    with open(out_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["ri", "field", "definition"])
        writer.writeheader()
        writer.writerows(all_fields)
    print(f"Saved {len(all_fields)} fields to {out_file}")

if __name__ == "__main__":
    main()
