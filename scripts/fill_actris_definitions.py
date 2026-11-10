"""One-off: fill outputs/dictionary_actris_terms.csv from ACTRIS_vocabulary.ttl (CC0)."""
from collections import defaultdict
from pathlib import Path

import pandas as pd
from rdflib import Graph, Namespace

SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
TTL = "data/raw/dictionary_vocabularies/actris_vocab/ACTRIS_vocabulary.ttl"
CSV = "outputs/dictionary_actris_terms.csv"
MARKER = "[NO DEFINITION PUBLISHED in actris_vocab]"
DEF_COL = "Definition (if published)"

g = Graph(); g.parse(TTL)
exact  = defaultdict(list)   # label as-is -> [(uri, defn_or_None)]
folded = defaultdict(list)   # label.lower() -> [...]
for s, o in g.subject_objects(SKOS.prefLabel):
    label = str(o)
    uri = str(s)
    defs = list(g.objects(s, SKOS.definition))
    defn = str(defs[0]).strip() if defs else None
    exact[label].append((uri, defn))
    folded[label.lower()].append((uri, defn))

df = pd.read_csv(CSV, keep_default_na=False)
df["candidate_uris"] = ""
df["matched_by"] = ""

c = dict(matched_single_with_def=0, matched_single_without_def=0,
         ambiguous_exact=0, unmatched_exact=0,
         if_folded_would_match=0, if_folded_would_be_ambiguous=0)

for idx, row in df.iterrows():
    label = str(row["Term Label"]).strip()
    hits = exact.get(label, [])
    folded_hits = folded.get(label.lower(), [])

    if len(hits) == 1:
        uri, defn = hits[0]
        df.at[idx, "Term URI"] = uri
        df.at[idx, "matched_by"] = "prefLabel"
        if defn:
            df.at[idx, DEF_COL] = defn
            c["matched_single_with_def"] += 1
        else:
            df.at[idx, DEF_COL] = MARKER
            c["matched_single_without_def"] += 1
        if len(folded_hits) > 1:
            c["if_folded_would_be_ambiguous"] += 1
    elif len(hits) > 1:
        df.at[idx, "candidate_uris"] = "; ".join(u for u, _ in hits)
        df.at[idx, DEF_COL] = f"[AMBIGUOUS: prefLabel matches {len(hits)} concepts]"
        df.at[idx, "matched_by"] = "prefLabel_ambiguous"
        c["ambiguous_exact"] += 1
    else:
        df.at[idx, DEF_COL] = MARKER
        df.at[idx, "matched_by"] = ""
        c["unmatched_exact"] += 1
        if len(folded_hits) == 1:
            c["if_folded_would_match"] += 1
        elif len(folded_hits) > 1:
            c["if_folded_would_be_ambiguous"] += 1

df.to_csv(CSV, index=False)
print(f"total rows: {len(df)}")
for k, v in c.items():
    print(f"  {k}: {v}")
