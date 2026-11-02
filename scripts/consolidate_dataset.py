import pandas as pd
from pathlib import Path

OUT = Path("outputs")
fields_file = OUT / "field_comparison_dataset.csv"
defs_file = OUT / "definitions_extracted.csv"
out_file = OUT / "final_field_comparison.csv"

print("Loading datasets...")
df_fields = pd.read_csv(fields_file)
df_defs = pd.read_csv(defs_file) if defs_file.exists() else pd.DataFrame(columns=["ri", "field", "definition"])

# Clean up the field names for matching (remove array brackets like [0])
df_fields['clean_field'] = df_fields['field'].str.replace(r'\[\d+\]', '', regex=True)

# Merge definitions where they exist
merged = df_fields.merge(df_defs, on=["ri", "field"], how="left", suffixes=("", "_def"))

# If a definition exists in the defs file, use it. Otherwise, keep the flagged one or flag it.
def set_definition(row):
    if pd.notna(row['definition_def']) and str(row['definition_def']).strip() != "":
        return row['definition_def']
    elif pd.notna(row['definition']) and str(row['definition']).startswith("FLAGGED"):
        return row['definition']
    else:
        return "FLAGGED: No published API definition found"

merged['final_definition'] = merged.apply(set_definition, axis=1)

# Keep only the necessary columns
final_df = merged[['ri', 'field', 'final_definition']].rename(columns={'final_definition': 'definition'})
final_df.to_csv(out_file, index=False)

print(f"Saved {len(final_df)} fields to {out_file}")
print("\nCount of fields with actual definitions vs flagged:")
print(final_df.assign(is_flagged=final_df['definition'].str.startswith('FLAGGED')).groupby(['ri', 'is_flagged']).size())
