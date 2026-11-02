import pandas as pd
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sentence_transformers import SentenceTransformer
from pathlib import Path
from itertools import combinations
import json
from datetime import datetime

OUT = Path("outputs")
in_file = OUT / "final_field_comparison.csv"
out_file = OUT / "field_candidate_rankings.csv"
manifest_file = OUT / "field_candidate_rankings_run.json"

print("Loading data...")
df = pd.read_csv(in_file)

# Group fields by RI (all three)
fields_by_ri = {ri: grp['field'].tolist() for ri, grp in df.groupby('ri')}
for ri in ["DEIMS", "ICOS", "ACTRIS"]:
    print(f"  {ri}: {len(fields_by_ri.get(ri, []))} fields")

# Fixed ordering so the pair order in output is stable
all_ris = ["DEIMS", "ICOS", "ACTRIS"]
all_fields = []
ri_slices = {}
offset = 0
for ri in all_ris:
    f = fields_by_ri[ri]
    ri_slices[ri] = (offset, offset + len(f))
    all_fields.extend(f)
    offset += len(f)
print(f"Total fields: {len(all_fields)}")

# TF-IDF fit once on all fields, so vocabulary is shared across RIs
print("Computing TF-IDF...")
vectorizer = TfidfVectorizer(token_pattern=r'(?u)\b\w+\b')
tfidf_matrix = vectorizer.fit_transform(all_fields)

# MiniLM embed once on all fields
print("Computing MiniLM embeddings...")
model_name = "sentence-transformers/all-MiniLM-L6-v2"
model = SentenceTransformer(model_name)
emb = model.encode(all_fields, show_progress_bar=False)

# Pairwise over all three RI combinations
print("Building rankings...")
results = []
for ri_a, ri_b in combinations(all_ris, 2):
    a_slice = slice(*ri_slices[ri_a])
    b_slice = slice(*ri_slices[ri_b])
    tfidf_sim = cosine_similarity(tfidf_matrix[a_slice], tfidf_matrix[b_slice])
    minilm_sim = cosine_similarity(emb[a_slice], emb[b_slice])
    fields_a = fields_by_ri[ri_a]
    fields_b = fields_by_ri[ri_b]
    print(f"  {ri_a} x {ri_b}: {len(fields_a) * len(fields_b)} pairs")
    for i, fa in enumerate(fields_a):
        for j, fb in enumerate(fields_b):
            results.append({
                "ri_a": ri_a,
                "field_a": fa,
                "ri_b": ri_b,
                "field_b": fb,
                "tfidf_score": round(float(tfidf_sim[i][j]), 4),
                "minilm_score": round(float(minilm_sim[i][j]), 4),
            })

results_df = pd.DataFrame(results).sort_values(by="minilm_score", ascending=False).reset_index(drop=True)
results_df.to_csv(out_file, index=False)

pair_counts = {f"{k[0]}-{k[1]}": int(v) for k, v in results_df.groupby(['ri_a', 'ri_b']).size().items()}

manifest = {
    "timestamp": datetime.now().isoformat(),
    "minilm_model": model_name,
    "ri_field_counts": {ri: len(fields_by_ri[ri]) for ri in all_ris},
    "pair_counts": pair_counts,
    "total_pairs": len(results),
    "output_file": str(out_file),
}
with open(manifest_file, "w") as f:
    json.dump(manifest, f, indent=2)

print(f"Saved {len(results)} pairs to {out_file}")
print(f"Pair counts: {pair_counts}")
print("Top 5 pairs by MiniLM:")
print(results_df.head(5).to_string(index=False))
