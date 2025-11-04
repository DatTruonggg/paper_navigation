from neo4j import GraphDatabase
from tqdm import tqdm
from sklearn.metrics.pairwise import cosine_similarity
from scipy.sparse import csr_matrix

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from logs import log

NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASS = "neo4j123"

LIMIT_PAPERS = 100000
MIN_SIMILARITY = 0.45
ALPHA = 0.5
BETA = 0.5

BATCH_SIZE = os.getenv("BATCH_SIZE")

# CLASS DEFINITION
class SemanticGraphBuilderCosine:
    def __init__(self, uri, user, password):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self.driver.close()

    # Load paper citations (references)
    def load_citations(self, limit=LIMIT_PAPERS):
        with self.driver.session() as session:
            log.info("Loading citation data from Neo4j...")
            result = session.run(f"""
                MATCH (p:Paper)-[:CITES]->(r:Paper)
                WITH p, collect(r.id) AS refs
                RETURN p.id AS pid, refs
                LIMIT {limit}
            """)
            refs_map = {row["pid"]: row["refs"] for row in result}
            log.info(f"Loaded {len(refs_map)} papers.")
            return refs_map

    # Build binary matrix for cosine similarity
    def build_matrix(self, refs_map):
        all_refs = sorted({r for refs in refs_map.values() for r in refs})
        ref_index = {rid: i for i, rid in enumerate(all_refs)}
        n_papers = len(refs_map)
        n_refs = len(all_refs)
        log.info(f"Building matrix of size {n_papers} x {n_refs}")

        rows, cols, data = [], [], []
        paper_ids = list(refs_map.keys())
        for i, pid in enumerate(paper_ids):
            for rid in refs_map[pid]:
                if rid in ref_index:
                    rows.append(i)
                    cols.append(ref_index[rid])
                    data.append(1)
        mat = csr_matrix((data, (rows, cols)), shape=(n_papers, n_refs))
        return paper_ids, mat

    # Compute cosine similarity
    def compute_cosine(self, paper_ids, mat, batch_size=BATCH_SIZE):
        log.info(f"Computing cosine similarity in batches of {batch_size}...")
        n = mat.shape[0]
        pairs = {}
        for start in range(0, n, batch_size):
            end = min(start + batch_size, n)
            sub_mat = mat[start:end]
            cos_sim = cosine_similarity(sub_mat, mat, dense_output=False)

            for i, j in zip(*cos_sim.nonzero()):
                if cos_sim[i, j] >= MIN_SIMILARITY and (start + i) < j:
                    pairs[(paper_ids[start + i], paper_ids[j])] = float(cos_sim[i, j])

            log.info(f"Processed rows {start}-{end} -> total {len(pairs)} strong pairs so far.")
        return pairs
    
    # Write edges back to Neo4j

    def write_edges(self, pairs, rel_type="SIMILAR_TO", weight_factor=1.0):
        with self.driver.session() as session:
            log.info(f"Writing {len(pairs)} edges to Neo4j...")
            for (a, b), sim in tqdm(pairs.items()):
                session.run(f"""
                    MATCH (p1:Paper {{id:$a}}), (p2:Paper {{id:$b}})
                    MERGE (p1)-[r:{rel_type}]->(p2)
                    SET r.weight = $w
                """, a=a, b=b, w=sim * weight_factor)
        log.info("Done writing edges.")

    
    # Full build (Coupling + Co-citation)
    def build(self):
        # --- Bibliographic Coupling ---
        refs_map = self.load_citations()
        paper_ids, mat_refs = self.build_matrix(refs_map)
        coupling = self.compute_cosine(paper_ids, mat_refs)

        # --- Co-citation ---
        # Reverse mapping: who cites whom
        citers_map = {}
        for paper, refs in refs_map.items():
            for ref in refs:
                citers_map.setdefault(ref, []).append(paper)
        paper_ids, mat_citers = self.build_matrix(citers_map)
        cocitation = self.compute_cosine(paper_ids, mat_citers)

        # --- Merge ---
        all_pairs = set(coupling.keys()) | set(cocitation.keys())
        merged = {}
        for p in all_pairs:
            merged[p] = ALPHA * coupling.get(p, 0) + BETA * cocitation.get(p, 0)

        self.write_edges(merged, rel_type="SIMILAR_TO")

if __name__ == "__main__":
    builder = SemanticGraphBuilderCosine(NEO4J_URI, NEO4J_USER, NEO4J_PASS)
    try:
        builder.build()
    finally:
        builder.close()