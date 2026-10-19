import matplotlib.pyplot as plt
import networkx as nx
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "outputs/hyytiala_candidates.csv"
OUT_PATH = ROOT / "outputs/hyytiala_network.png"

def main():
    df = pd.read_csv(CSV_PATH)
    G = nx.Graph()

    # Define nodes with their RI as a category
    nodes = {
        "ko6m": "ACTRIS",
        "SMR": "ICOS",
        "FI-Hyy": "ICOS",
        "663dac80-211d-4c19-a356-04ee0da0f0eb": "eLTER"
    }
    
    for n, ri in nodes.items():
        G.add_node(n, ri=ri)

    # Human-readable node labels. The DEIMS UUID stays the node key so the
    # edges still resolve by source_id; the UUID is too long to draw.
    node_labels = {
        "ko6m": "ko6m",
        "SMR": "SMR",
        "FI-Hyy": "FI-Hyy",
        "663dac80-211d-4c19-a356-04ee0da0f0eb": "eLTER SMEAR II",
    }

    # Add edges from our crosswalk
    for _, row in df.iterrows():
        G.add_edge(row['source_id_a'], row['source_id_b'], distance=row['distance_km_dbscan'], label=row['same_place'])

    # Draw
    plt.figure(figsize=(10, 6))
    
    # Color map by RI
    color_map = []
    for node in G:
        ri = G.nodes[node]['ri']
        if ri == "ACTRIS": color_map.append("#d62728") # red
        elif ri == "ICOS": color_map.append("#2ca02c") # green
        elif ri == "eLTER": color_map.append("#1f77b4") # blue

    pos = nx.spring_layout(G, seed=42)
    
    nx.draw(G, pos, labels=node_labels, with_labels=True, node_color=color_map, node_size=4000, font_size=9, font_weight="bold", font_color="white")
    
    # Edge labels (distances)
    edge_labels = {(u, v): f"{d['distance']:.2f} km" for u, v, d in G.edges(data=True)}
    nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, font_size=8)

    plt.title("Hyytiälä Crosswalk Network (Nodes colored by Research Infrastructure)")
    plt.savefig(OUT_PATH, bbox_inches="tight")
    print(f"Saved visual to {OUT_PATH}")

if __name__ == "__main__":
    main()