import json
import csv
import requests
from pathlib import Path

OUT = Path("outputs")
OUT.mkdir(exist_ok=True)

def get_deims_defs():
    print("Fetching DEIMS schema definitions...")
    # DEIMS has a schema endpoint that defines the fields
    try:
        resp = requests.get("https://deims.org/api/sites/schema", timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            results = []
            def walk(schema, prefix=""):
                if isinstance(schema, dict) and "properties" in schema:
                    for k, v in schema["properties"].items():
                        p = f"{prefix}.{k}" if prefix else k
                        desc = v.get("description", "FLAGGED: No published API definition found")
                        results.append({"ri": "DEIMS", "field": p, "definition": desc})
                        walk(v, p)
            walk(data)
            if results:
                print(f"  Found {len(results)} DEIMS definitions.")
                return results
    except Exception as e:
        print(f"  DEIMS schema endpoint failed: {e}")
    return []

def get_icos_defs():
    print("Fetching ICOS ontology definitions...")
    query = """
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
    SELECT DISTINCT ?p ?comment WHERE {
      ?s ?p ?o .
      ?s a <http://meta.icos-cp.eu/ontologies/cpmeta/Station> .
      OPTIONAL { ?p rdfs:comment ?comment }
      OPTIONAL { ?p skos:definition ?comment }
    }
    """
    try:
        resp = requests.get("https://meta.icos-cp.eu/sparql", params={"query": query, "format": "application/sparql-results+json"}, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            results = []
            for b in data["results"]["bindings"]:
                p = b["p"]["value"].split("/")[-1]
                comment = b.get("comment", {}).get("value", "FLAGGED: No published API definition found")
                results.append({"ri": "ICOS", "field": p, "definition": comment})
            # Deduplicate
            seen = set()
            unique = []
            for r in results:
                if r["field"] not in seen:
                    seen.add(r["field"])
                    unique.append(r)
            print(f"  Found {len(unique)} ICOS definitions.")
            return unique
    except Exception as e:
        print(f"  ICOS SPARQL failed: {e}")
    return []

def get_actris_defs():
    print("Fetching ACTRIS definitions...")
    # Try the specific Facility schema in OpenAPI
    try:
        resp = requests.get("https://prod-actris-md.nilu.no/v3/api-docs", timeout=30)
        resp.raise_for_status()
        data = resp.json()
        schemas = data.get("components", {}).get("schemas", {})
        
        results = []
        # Check all schemas for facility-like ones
        for name, schema in schemas.items():
            if "Facility" in name or "Site" in name:
                for prop, details in schema.get("properties", {}).items():
                    desc = details.get("description", "FLAGGED: No published API definition found")
                    results.append({"ri": "ACTRIS", "field": prop, "definition": desc})
        
        # Deduplicate by field name
        seen = set()
        unique = []
        for r in results:
            if r["field"] not in seen:
                seen.add(r["field"])
                unique.append(r)
        print(f"  Found {len(unique)} ACTRIS definitions.")
        return unique
    except Exception as e:
        print(f"  ACTRIS API failed: {e}")
    return []

def main():
    all_fields = []
    all_fields.extend(get_deims_defs())
    all_fields.extend(get_icos_defs())
    all_fields.extend(get_actris_defs())

    out_file = OUT / "definitions_extracted.csv"
    with open(out_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["ri", "field", "definition"])
        writer.writeheader()
        writer.writerows(all_fields)
    print(f"Saved {len(all_fields)} definitions to {out_file}")

if __name__ == "__main__":
    main()
