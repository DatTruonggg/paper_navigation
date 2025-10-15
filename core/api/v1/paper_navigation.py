from fastapi import APIRouter, HTTPException
from neo4j import GraphDatabase
from typing import Dict, List

# ===== CONFIG =====
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASS = "neo4j123"
DB_NAME = "webofpapers"

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
router = APIRouter()

# ===== UTIL =====
def run_query(query: str, params: Dict = {}, as_data: bool = False):

    with driver.session(database=DB_NAME) as session:
        result = session.run(query, **params)
        if as_data:
            return [r.data() for r in result]
        else:
            records = list(result)  # fetch all records before session closes
            return records

# ===== API ROUTES =====

@router.get("/api/v1/navigation/paper/{paper_id}")
def get_paper_neighbors(paper_id: str):
    """
    Retrieve a paper and its connected entities (authors, topics, citations, etc.)
    """
    query = """
    MATCH (p:Paper {id:$paper_id})
    OPTIONAL MATCH (p)-[r]-(n)
    RETURN p, collect(DISTINCT n) AS neighbors, collect(DISTINCT type(r)) AS relations
    """
    result = run_query(query, {"paper_id": paper_id}, as_data=True)
    
    if not result:
        raise HTTPException(status_code=404, detail="Paper not found")

    data = result[0]
    paper = data["p"]
    neighbors = data["neighbors"]
    rel_types = data["relations"]

    return {
        "paper": paper,
        "connected_nodes": neighbors,
        "relation_types": rel_types,
        "total_neighbors": len(neighbors)
    }

@router.get("/api/v1/navigation/graph/{graph_id}")
def get_graph(graph_id: str):
    """
    Retrieve a semantic subgraph for visualization or local exploration.
    """
    query = """
    MATCH (p:Paper {id:$graph_id})-[r*1..2]-(n)
    WITH collect(DISTINCT p) + collect(DISTINCT n) AS nodes, collect(DISTINCT r) AS rels
    RETURN nodes, rels
    """
    result = run_query(query, {"graph_id": graph_id}, as_data=False)

    if not result:
        raise HTTPException(status_code=404, detail="Graph not found or too small")

    record = result[0]
    nodes = [{"id": n["id"], "label": list(n.labels)[0], **dict(n)} for n in record["nodes"]]
    relationships = [
        {"type": r.type, "start": r.start_node["id"], "end": r.end_node["id"]}
        for path in record["rels"] for r in path
    ]

    return {
        "graph_id": graph_id,
        "nodes": nodes,
        "edges": relationships,
        "node_count": len(nodes),
        "edge_count": len(relationships)
    }