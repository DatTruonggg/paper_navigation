from fastapi import APIRouter, HTTPException
from neo4j import GraphDatabase
from typing import Dict

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', '..')) #quick fix path
from core.id_mapper import get_paper_mappings

from dotenv import load_dotenv
load_dotenv()

# config
NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USER = os.getenv("NEO4J_USER")
NEO4J_PASS = os.getenv("NEO4J_PASSWORD")
DB_NAME = os.getenv("DB_NAME")

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
router = APIRouter(tags=["Navigation"])

def run_query(query: str, params: Dict = {}, as_data: bool = False):
    with driver.session(database=DB_NAME) as session:
        result = session.run(query, **params)
        if as_data:
            return [r.data() for r in result]
        else:
            return list(result)

# API capabilities for paper navigation
@router.get("/paper/{paper_id}/similar")
def get_similar_papers(paper_id: str, top_k: int = 30):
    """
    Retrieve top-K most similar papers using SIMILAR_TO edges.
    Used for semantic navigation and recommendation.
    """
    try:
        mapped = get_paper_mappings(paper_id)
        paper_id = mapped.get("oa_paper_id", paper_id)
    except Exception:
        paper_id = paper_id

    query = """
    MATCH (p:Paper {id:$paper_id})-[r:SIMILAR_TO]-(n:Paper)
    RETURN n AS neighbor, r.weight AS weight
    ORDER BY weight DESC
    LIMIT $top_k
    """
    result = run_query(query, {"paper_id": paper_id, "top_k": top_k}, as_data=True)
    if not result:
        raise HTTPException(status_code=404, detail="No similar papers found")

    return {
        "paper_id": paper_id,
        "similar_papers": [
            {"id": r["neighbor"]["id"], 
             "title": r["neighbor"].get("title"), 
             "weight": r["weight"]}
            for r in result
        ],
        "total": len(result),
    }

@router.get("/graph/{paper_id}")
def get_navigation_graph(paper_id: str, mode: str = "semantic", top_k: int = 30):
    """
    Return a lightweight semantic/citation/hybrid subgraph centered on a paper.
    mode: 'semantic' | 'citation' | 'hybrid'
    """
    try:
        mapped = get_paper_mappings(paper_id)
        paper_id = mapped.get("oa_paper_id", paper_id)
    except Exception:
        paper_id = paper_id
    if mode == "semantic":
        query = """
        MATCH (p:Paper {id:$paper_id})-[r:SIMILAR_TO]-(n:Paper)
        WITH p, n, r
        ORDER BY r.weight DESC LIMIT $top_k
        RETURN collect(DISTINCT p) + collect(DISTINCT n) AS nodes, collect(DISTINCT r) AS rels
        """
    elif mode == "citation":
        query = """
        MATCH (p:Paper {id:$paper_id})-[r:CITES]-(n:Paper)
        RETURN collect(DISTINCT p) + collect(DISTINCT n) AS nodes, collect(DISTINCT r) AS rels
        """
    elif mode == "hybrid":
        query = """
        MATCH (p:Paper {id:$paper_id})
        OPTIONAL MATCH (p)-[r1:SIMILAR_TO]-(n1:Paper)
        OPTIONAL MATCH (p)-[r2:CITES]-(n2:Paper)
        WITH collect(DISTINCT p) + collect(DISTINCT n1) + collect(DISTINCT n2) AS nodes,
             collect(DISTINCT r1) + collect(DISTINCT r2) AS rels
        RETURN nodes, rels
        """
    else:
        raise HTTPException(status_code=400, detail="Invalid mode. Use 'semantic', 'citation', or 'hybrid'.")

    result = run_query(query, {"paper_id": paper_id, "top_k": top_k}, as_data=False)
    if not result:
        raise HTTPException(status_code=404, detail="No subgraph found")

    record = result[0]
    nodes = [
        {"id": n["id"], 
         "title": n.get("title"), 
         "year": n.get("year"), 
         "label": list(n.labels)[0]}
        for n in record["nodes"]
    ]

    edges = []
    for r in record["rels"]:
        try:
            edges.append({
                "type": r.type,
                "start": r.start_node["id"],
                "end": r.end_node["id"],
                "weight": r.get("weight", None)
            })
        except Exception:
            continue

    return {
        "paper_id": paper_id,
        "mode": mode,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": nodes,
        "edges": edges,
    }