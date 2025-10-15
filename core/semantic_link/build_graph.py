import requests
from tqdm import tqdm
from typing import Dict, List
from neo4j import GraphDatabase

# ===== CONFIG =====
OPENALEX_API = "https://api.openalex.org/works"
MAX_PAPERS = 1000
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASS = "neo4j123"

# Focus area (NLP)
NLP_TOPICS = [
    "T10181",  # Natural Language Processing Techniques
]

# ===== SETUP =====
driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))

# ====== NEO4J SCHEMA ======
def create_constraints(tx):
    constraints = [
        "CREATE CONSTRAINT paper_id IF NOT EXISTS FOR (p:Paper) REQUIRE p.id IS UNIQUE",
        "CREATE CONSTRAINT author_id IF NOT EXISTS FOR (a:Author) REQUIRE a.id IS UNIQUE",
        "CREATE CONSTRAINT inst_id IF NOT EXISTS FOR (i:Institution) REQUIRE i.id IS UNIQUE",
        "CREATE CONSTRAINT topic_id IF NOT EXISTS FOR (t:Topic) REQUIRE t.id IS UNIQUE",
        "CREATE CONSTRAINT concept_id IF NOT EXISTS FOR (c:Concept) REQUIRE c.id IS UNIQUE",
        "CREATE CONSTRAINT keyword_name IF NOT EXISTS FOR (k:Keyword) REQUIRE k.name IS UNIQUE",
        "CREATE CONSTRAINT goal_id IF NOT EXISTS FOR (g:Goal) REQUIRE g.id IS UNIQUE",
        "CREATE CONSTRAINT venue_id IF NOT EXISTS FOR (v:Venue) REQUIRE v.id IS UNIQUE"
    ]
    for q in constraints:
        tx.run(q)
    tx.run("CREATE INDEX paper_title IF NOT EXISTS FOR (p:Paper) ON (p.title)")
    
# ====== HELPERS ======
def safe_id(url: str) -> str:
    return url.split("/")[-1] if url else None

def process_institution(inst: Dict) -> Dict:
    return {
        "id": safe_id(inst.get("id")),
        "name": inst.get("display_name", ""),
        "ror": inst.get("ror"),
        "country_code": inst.get("country_code"),
        "type": inst.get("type"),
    }

def process_concept(c: Dict) -> Dict:
    return {
        "id": safe_id(c.get("id")),
        "name": c.get("display_name", ""),
        "level": c.get("level"),
        "score": c.get("score", 1.0),
        "wikidata": c.get("wikidata"),
    }

def process_topic(t: Dict) -> Dict:
    return {
        "id": safe_id(t.get("id")),
        "name": t.get("display_name", ""),
        "score": t.get("score", 1.0),
        "field": t.get("field", {}).get("display_name"),
        "subfield": t.get("subfield", {}).get("display_name"),
    }

# ===== FETCH =====
def fetch_nlp_papers(max_papers: int) -> List[Dict]:
    """Fetch NLP-related papers from OpenAlex"""
    topic_filter = "|".join(NLP_TOPICS) #TODO: Check if this works needed OR logic
    url = f"{OPENALEX_API}?filter=topics.id:{topic_filter}&per-page=50&select=id,title,publication_year,doi,primary_location,cited_by_count,publication_date,type,is_paratext,is_retracted,abstract_inverted_index,authorships,concepts,topics,keywords,referenced_works,related_works,sustainable_development_goals,primary_topic"
    papers, cursor = [], "*"
    while cursor and len(papers) < max_papers:
        try:
            r = requests.get(f"{url}&cursor={cursor}")
            r.raise_for_status()
            data = r.json()
            papers.extend(data["results"])
            cursor = data.get("meta", {}).get("next_cursor")
            print(f"Fetched {len(papers)} papers...")
        except Exception as e:
            print("Error fetching papers:", e)
            break
    return papers[:max_papers]

# ===== IMPORT LOGIC =====
def import_paper(tx, paper: Dict):
    pid = safe_id(paper.get("id"))
    if not pid:
        return

    # --- Paper node (ensure exists) ---
    tx.run("""
        MERGE (p:Paper {id:$id})
        SET p.title=$title,
            p.year=$year,
            p.doi=$doi,
            p.url=$url,
            p.cited_by_count=$citations,
            p.publication_date=$pub_date,
            p.type=$type,
            p.is_paratext=$is_paratext,
            p.is_retracted=$is_retracted
    """, id=pid,
           title=paper.get("title"),
           year=paper.get("publication_year"),
           doi=paper.get("doi"),
           url=paper.get("primary_location", {}).get("landing_page_url"),
           citations=paper.get("cited_by_count", 0),
           pub_date=paper.get("publication_date"),
           type=paper.get("type"),
           is_paratext=paper.get("is_paratext", False),
           is_retracted=paper.get("is_retracted", False))

    # --- Authors + Institutions ---
    authors = []
    for au in paper.get("authorships", []):
        a = au.get("author")
        if not a or not a.get("id"):
            continue
        aid = safe_id(a["id"])
        tx.run("""
            MERGE (a:Author {id:$id})
            SET a.name=$name, a.orcid=$orcid
            WITH a
            MATCH (p:Paper {id:$pid})
            MERGE (a)-[:AUTHORED]->(p)
        """, id=aid, name=a.get("display_name"), orcid=a.get("orcid"), pid=pid)
        authors.append(aid)

        for inst in au.get("institutions", []):
            inst_data = process_institution(inst)
            if not inst_data["id"]:
                continue
            tx.run("""
                MERGE (i:Institution {id:$id})
                SET i.name=$name, i.ror=$ror, i.country_code=$cc, i.type=$type
                WITH i
                MATCH (a:Author {id:$aid})
                MERGE (a)-[:AFFILIATED_WITH]->(i)
            """, id=inst_data["id"], name=inst_data["name"], ror=inst_data["ror"],
                   cc=inst_data["country_code"], type=inst_data["type"], aid=aid)

    # --- Co-author relationships ---
    for i in range(len(authors)):
        for j in range(i + 1, len(authors)):
            tx.run("""
                MATCH (a1:Author {id:$a1}), (a2:Author {id:$a2})
                MERGE (a1)-[:CO_AUTHOR_WITH]->(a2)
                MERGE (a2)-[:CO_AUTHOR_WITH]->(a1)
            """, a1=authors[i], a2=authors[j])

    # --- Topics ---
    for t in paper.get("topics", []):
        td = process_topic(t)
        if not td["id"]:
            continue
        tx.run("""
            MERGE (t:Topic {id:$id})
            SET t.name=$name, t.score=$score, t.field=$field, t.subfield=$subfield
            WITH t
            MATCH (p:Paper {id:$pid})
            MERGE (p)-[:HAS_TOPIC {score:$score}]->(t)
        """, pid=pid, **td)

    # --- Primary topic ---
    pt = paper.get("primary_topic")
    if pt and pt.get("id"):
        tpid = safe_id(pt["id"])
        tx.run("""
            MERGE (t:Topic {id:$id})
            SET t.name=$name
            WITH t
            MATCH (p:Paper {id:$pid})
            MERGE (p)-[:HAS_PRIMARY_TOPIC]->(t)
        """, id=tpid, name=pt.get("display_name"), pid=pid)

    # --- Concepts ---
    for c in paper.get("concepts", []):
        cd = process_concept(c)
        if not cd["id"]:
            continue
        tx.run("""
            MERGE (c:Concept {id:$id})
            SET c.name=$name, c.level=$level, c.score=$score, c.wikidata=$wikidata
            WITH c
            MATCH (p:Paper {id:$pid})
            MERGE (p)-[:HAS_CONCEPT {score:$score}]->(c)
        """, pid=pid, **cd)

    # --- Keywords --- 
    for kw in paper.get("keywords", []):
        kname = kw.get("display_name", "").strip().lower()
        if not kname:
            continue
        tx.run("""
            MERGE (k:Keyword {name:$name})
            WITH k
            MATCH (p:Paper {id:$pid})
            MERGE (p)-[:HAS_KEYWORD {score:$score}]->(k)
        """, name=kname, pid=pid, score=kw.get("score", 1.0))

    # --- Sustainable Goals ---
    for g in paper.get("sustainable_development_goals", []):
        gid = safe_id(g.get("id"))
        if not gid:
            continue
        tx.run("""
            MERGE (g:Goal {id:$id})
            SET g.name=$name
            WITH g
            MATCH (p:Paper {id:$pid})
            MERGE (p)-[:ALIGNS_WITH {score:$score}]->(g)
        """, id=gid, name=g.get("display_name"), pid=pid, score=g.get("score", 1.0))

    # Store references for later processing
    return {
        "id": pid,
        "references": [safe_id(ref) for ref in paper.get("referenced_works", [])[:50] if safe_id(ref)],
        "related_works": [safe_id(rw) for rw in paper.get("related_works", [])[:30] if safe_id(rw)]
    }

def create_connections(tx, paper_data):
    """Create citation and related work connections after all papers are imported"""
    pid = paper_data["id"]
    
    # --- Citations ---
    for rid in paper_data["references"]:
        tx.run("""
            MATCH (a:Paper {id:$pid})
            MATCH (b:Paper {id:$rid})
            MERGE (a)-[:CITES]->(b)
        """, pid=pid, rid=rid)

    # --- Related Works (semantic edges) ---
    for rid in paper_data["related_works"]:
        tx.run("""
            MATCH (a:Paper {id:$pid})
            MATCH (b:Paper {id:$rid})
            MERGE (a)-[:RELATED_TO]->(b)
        """, pid=pid, rid=rid)

# ===== MAIN =====
def main():
    print("Building Full Semantic Graph from OpenAlex...")

    with driver.session(database="webofpapers") as s:
        s.execute_write(create_constraints)
        print("Created database constraints")

    import time
    time.sleep(3)  # Wait for constraints to be created

    papers = fetch_nlp_papers(MAX_PAPERS)
    print(f"Fetched {len(papers)} papers")
    
    # Print sample paper data for debugging
    if papers:
        print("\nSample paper data:")
        sample = papers[0]
        print(f"Title: {sample.get('title')}")
        print(f"ID: {sample.get('id')}")
        print(f"Authors: {len(sample.get('authorships', []))}")
        print(f"Topics: {len(sample.get('topics', []))}")
        print(f"Concepts: {len(sample.get('concepts', []))}")
        print(f"References: {len(sample.get('referenced_works', []))}")
        print(f"Related works: {len(sample.get('related_works', []))}")

    # First pass: Import all papers and their properties
    paper_connections = []
    with driver.session(database="webofpapers") as s:
        for i, paper in enumerate(tqdm(papers, desc="Importing papers")):
            try:
                conn_data = s.execute_write(import_paper, paper)
                if conn_data:
                    paper_connections.append(conn_data)
                if i % 5 == 0:  # Progress update every 5 papers
                    print(f"Imported {i+1} papers, {len(paper_connections)} connection records created")
            except Exception as e:
                print(f"Import error for paper {i+1}:", e)
                continue
    
    print(f"\nCreated {len(paper_connections)} paper records with connection data")
    
    # Second pass: Create connections between papers
    with driver.session(database="webofpapers") as s:
        for i, conn_data in enumerate(tqdm(paper_connections, desc="Creating connections")):
            try:
                s.execute_write(create_connections, conn_data)
                if i % 10 == 0:  # Progress update every 10 connections
                    print(f"Processed connections for {i+1} papers")
            except Exception as e:
                print(f"Connection error for paper {i+1}:", e)
                continue

    # Print final statistics
    with driver.session(database="webofpapers") as s:
        paper_count = s.run("MATCH (p:Paper) RETURN count(p) as count").single()["count"]
        author_count = s.run("MATCH (a:Author) RETURN count(a) as count").single()["count"]
        topic_count = s.run("MATCH (t:Topic) RETURN count(t) as count").single()["count"]
        citation_count = s.run("MATCH ()-[r:CITES]->() RETURN count(r) as count").single()["count"]
        related_count = s.run("MATCH ()-[r:RELATED_TO]->() RETURN count(r) as count").single()["count"]
        
        print(f"\nGraph build complete!")
        print(f"Statistics:")
        print(f"- Papers: {paper_count}")
        print(f"- Authors: {author_count}")
        print(f"- Topics: {topic_count}")
        print(f"- Citation relationships: {citation_count}")
        print(f"- Related work relationships: {related_count}")

if __name__ == "__main__":
    main()