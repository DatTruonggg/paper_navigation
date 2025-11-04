import os
import sys
import requests
import time
from typing import Dict, List, Optional
from tqdm import tqdm
from neo4j import GraphDatabase

# Add project root to path for logs module
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from logs import log

# ===== CONFIGURATION CONSTANTS =====
OPENALEX_API = os.getenv("OPENALEX_API")
MAX_PAPERS = os.getenv("MAX_PAPERS")

NLP_TOPICS = [
    "T10181",  # Natural Language Processing Techniques
    "T10028",  # Topic Modeling
    "T10201",  # Speech Recognition and Synthesis
    "T13083",  # Advanced Text Analysis Techniques
    "T11714",  # Multimodal Machine Learning Applications
    "T11307",  # Domain Adaptation and Few-Shot Learning
    "T12026",  # Explainable Artificial Intelligence (XAI)
    "T13629",  # Text Readability and Simplification
]

OA_STATUSES = ["green", "gold", "diamond", "hybrid", "closed", "bronze"]

# Environment variables for Neo4j connection
NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USER = os.getenv("NEO4J_USER")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE")

# Batch sizes for optimal performance
PAPER_BATCH_SIZE = 500
CITATION_BATCH_SIZE = 1000
AUTHOR_BATCH_SIZE = 1000
TOPIC_BATCH_SIZE = 500


class CitationGraphBuilder:
    """
    Builds citation graphs from OpenAlex data and stores them in Neo4j.
    """
    def __init__(self, uri: str, user: str, password: str, database: str = "webofpapers"):
        self.uri = uri
        self.user = user
        self.password = password
        self.database = database
        self.driver = None
        self._connect()

    def _connect(self) -> None:
        """Establish connection to Neo4j database."""
        try:
            self.driver = GraphDatabase.driver(
                self.uri,
                auth=(self.user, self.password)
            )
            # Test connection
            with self.driver.session(database=self.database) as session:
                session.run("RETURN 1")
            log.info(f"Connected to Neo4j at {self.uri}")
        except Exception as e:
            log.error(f"Failed to connect to Neo4j: {e}")
            raise

    def create_schema_constraints(self) -> None:
        """Create database constraints and indexes for optimal performance."""
        constraints = [
            "CREATE CONSTRAINT paper_id IF NOT EXISTS FOR (p:Paper) REQUIRE p.id IS UNIQUE",
            "CREATE CONSTRAINT author_id IF NOT EXISTS FOR (a:Author) REQUIRE a.id IS UNIQUE",
            "CREATE CONSTRAINT topic_id IF NOT EXISTS FOR (t:Topic) REQUIRE t.id IS UNIQUE",
            "CREATE INDEX paper_title IF NOT EXISTS FOR (p:Paper) ON (p.title)",
            "CREATE INDEX paper_year IF NOT EXISTS FOR (p:Paper) ON (p.year)",
            "CREATE INDEX author_name IF NOT EXISTS FOR (a:Author) ON (a.name)",
            "CREATE INDEX topic_name IF NOT EXISTS FOR (t:Topic) ON (t.name)",
        ]

        with self.driver.session(database=self.database) as session:
            for constraint in constraints:
                try:
                    session.run(constraint)
                    log.info(f"Applied constraint: {constraint}")
                except Exception as e:
                    log.warning(f"Constraint already exists or failed: {e}")

        time.sleep(2)

    def fetch_nlp_papers(self, max_papers: int = MAX_PAPERS) -> List[Dict]:
        """
        Fetch NLP-related open-access papers from OpenAlex.

        Args:
            max_papers: Maximum number of papers to fetch

        Returns:
            List of paper dictionaries from OpenAlex
        """
        log.info(f"Fetching up to {max_papers} NLP papers from OpenAlex...")

        topic_filter = "|".join(NLP_TOPICS)  # example: "T10181|T10028|T10201|T13083|T11714"
        oa_filter = "|".join(OA_STATUSES)    # example: "green|gold|diamond|hybrid"

        params = {
            "filter": f"topics.id:{topic_filter},open_access.oa_status:{oa_filter}",
            "per-page": 100,
            "select": (
                "id,title,publication_year,doi,open_access,publication_date,"
                "authorships,topics,referenced_works,cited_by_count,primary_location"
            ),
            "cursor": "*"
        }

        papers = []
        cursor = "*"

        with tqdm(total=max_papers, desc="Fetching papers") as pbar:
            while cursor and len(papers) < max_papers:
                try:
                    # Add debug logging to see cursor value
                    log.debug(f"Current cursor: {cursor}, Papers fetched: {len(papers)}")

                    if cursor != "*":
                        params['cursor'] = cursor

                    response = requests.get(OPENALEX_API, params=params, timeout=120)
                    response.raise_for_status()

                    data = response.json()
                    batch_papers = data.get("results", [])

                    if not batch_papers:
                        log.info("No more papers available")
                        break

                    papers.extend(batch_papers)
                    pbar.update(len(batch_papers))

                    cursor = data.get("meta", {}).get("next_cursor")

                    # Debug log to see if we got a next cursor
                    if len(papers) < 200:  # Only log for first few batches
                        log.info(f"Batch {len(papers)//100 + 1}: Got {len(batch_papers)} papers, next_cursor: {cursor}")

                    # Log progress
                    if len(papers) % 1000 == 0:
                        log.info(f"Fetched {len(papers)} papers...")

                except requests.exceptions.RequestException as e:
                    log.error(f"Request error: {e}")
                    break
                except Exception as e:
                    log.error(f"Unexpected error: {e}")
                    break

        return papers[:max_papers]

    def _safe_id(self, url: str) -> Optional[str]:
        """Extract ID from OpenAlex URL."""
        return url.split("/")[-1] if url and "/" in url else None

    def _process_paper_data(self, paper: Dict) -> Optional[Dict]:
        """Process paper data for database insertion."""
        paper_id = self._safe_id(paper.get("id"))
        if not paper_id:
            return None

        oa_info = paper.get("open_access", {}) or {}
        oa_status = oa_info.get("oa_status", "")
        oa_url = oa_info.get("oa_url", "")

        # --- Safe source extraction ---
        source_info = (paper.get("primary_location") or {}).get("source") or {}
        lineage = source_info.get("host_organization_lineage", [])
        source_value = lineage[0] if lineage else source_info.get("display_name", "")

        # --- Authors ---
        authors = []
        for authorship in paper.get("authorships", []):
            author = authorship.get("author", {})
            if author and author.get("id"):
                authors.append({
                    "id": self._safe_id(author["id"]),
                    "name": author.get("display_name", "")[:200],
                    "orcid": author.get("orcid", "")
                })

        # --- Topics ---
        topics = []
        for topic in paper.get("topics", []):
            if topic and topic.get("id"):
                topics.append({
                    "id": self._safe_id(topic["id"]),
                    "name": topic.get("display_name", "")[:200],
                    "score": topic.get("score", 1.0),
                    "field": topic.get("field", {}).get("display_name", "")[:100],
                    "subfield": topic.get("subfield", {}).get("display_name", "")[:100]
                })

        return {
            "id": paper_id,
            "title": (paper.get("title") or "")[:500],
            "year": paper.get("publication_year") or 0,
            "doi": paper.get("doi") or "",
            "oa_status": oa_status,
            "oa_url": oa_url,
            "source": source_value,
            "publication_date": paper.get("publication_date") or "",
            "cited_by_count": paper.get("cited_by_count", 0) or 0,
            "authors": authors,
            "topics": topics,
            "references": [
                self._safe_id(ref)
                for ref in (paper.get("referenced_works") or [])
                if self._safe_id(ref)
            ]
        }

    def create_paper_nodes(self, papers: List[Dict]) -> List[Dict]:
        """
        Create paper nodes in the database in batches.

        Args:
            papers: List of paper dictionaries

        Returns:
            List of processed papers with reference information
        """
        log.info("Creating paper nodes...")
        processed_papers = []

        with self.driver.session(database=self.database) as session:
            with tqdm(total=len(papers), desc="Creating paper nodes") as pbar:
                for i in range(0, len(papers), PAPER_BATCH_SIZE):
                    batch = papers[i:i + PAPER_BATCH_SIZE]
                    batch_data = []

                    for paper in batch:
                        processed = self._process_paper_data(paper)
                        if processed:
                            batch_data.append(processed)

                    if not batch_data:
                        pbar.update(len(batch))
                        continue

                    # Create paper nodes
                    query = """
                    UNWIND $papers AS paper
                    MERGE (p:Paper {id: paper.id})
                    SET p.title = paper.title,
                        p.year = paper.year,
                        p.doi = paper.doi,
                        p.oa_status = paper.oa_status,
                        p.oa_url = paper.oa_url,
                        p.source = paper.source,
                        p.publication_date = paper.publication_date,
                        p.cited_by_count = paper.cited_by_count
                    """

                    try:
                        session.run(query, papers=batch_data)
                        processed_papers.extend(batch_data)
                        pbar.update(len(batch))

                        if len(processed_papers) % 5000 == 0:
                            log.info(f"Created {len(processed_papers)} paper nodes...")

                    except Exception as e:
                        log.error(f"Error creating paper nodes batch: {e}")
                        pbar.update(len(batch))

        return processed_papers

    def create_author_nodes_and_relationships(self, papers: List[Dict]) -> None:
        """
        Create author nodes and AUTHORED relationships in batches.

        Args:
            papers: List of processed papers with author information
        """
        log.info("Creating author nodes and AUTHORED relationships...")

        # Collect all unique authors
        all_authors = {}
        for paper in papers:
            for author in paper.get("authors", []):
                author_id = author["id"]
                if author_id not in all_authors:
                    all_authors[author_id] = author

        # Create author nodes
        authors_list = list(all_authors.values())

        with self.driver.session(database=self.database) as session:
            with tqdm(total=len(authors_list), desc="Creating author nodes") as pbar:
                for i in range(0, len(authors_list), AUTHOR_BATCH_SIZE):
                    batch = authors_list[i:i + AUTHOR_BATCH_SIZE]

                    query = """
                    UNWIND $authors AS author
                    MERGE (a:Author {id: author.id})
                    SET a.name = author.name,
                        a.orcid = author.orcid
                    """

                    try:
                        session.run(query, authors=batch)
                        pbar.update(len(batch))
                    except Exception as e:
                        log.error(f"Error creating author nodes batch: {e}")
                        pbar.update(len(batch))

        # Create AUTHORED relationships
        log.info("Creating AUTHORED relationships...")
        authorships = []
        for paper in papers:
            paper_id = paper["id"]
            for author in paper.get("authors", []):
                authorships.append({
                    "paper_id": paper_id,
                    "author_id": author["id"]
                })

        with self.driver.session(database=self.database) as session:
            with tqdm(total=len(authorships), desc="Creating AUTHORED relationships") as pbar:
                for i in range(0, len(authorships), AUTHOR_BATCH_SIZE):
                    batch = authorships[i:i + AUTHOR_BATCH_SIZE]

                    query = """
                    UNWIND $authorships AS auth
                    MATCH (p:Paper {id: auth.paper_id})
                    MATCH (a:Author {id: auth.author_id})
                    MERGE (a)-[:AUTHORED]->(p)
                    """

                    try:
                        session.run(query, authorships=batch)
                        pbar.update(len(batch))
                    except Exception as e:
                        log.error(f"Error creating AUTHORED relationships batch: {e}")
                        pbar.update(len(batch))

    def create_topic_nodes_and_relationships(self, papers: List[Dict]) -> None:
        """
        Create topic nodes and HAS_TOPIC relationships in batches.

        Args:
            papers: List of processed papers with topic information
        """
        log.info("Creating topic nodes and HAS_TOPIC relationships...")

        # Collect all unique topics
        all_topics = {}
        for paper in papers:
            for topic in paper.get("topics", []):
                topic_id = topic["id"]
                if topic_id not in all_topics:
                    all_topics[topic_id] = topic

        # Create topic nodes
        topics_list = list(all_topics.values())

        with self.driver.session(database=self.database) as session:
            with tqdm(total=len(topics_list), desc="Creating topic nodes") as pbar:
                for i in range(0, len(topics_list), TOPIC_BATCH_SIZE):
                    batch = topics_list[i:i + TOPIC_BATCH_SIZE]

                    query = """
                    UNWIND $topics AS topic
                    MERGE (t:Topic {id: topic.id})
                    SET t.name = topic.name,
                        t.score = topic.score,
                        t.field = topic.field,
                        t.subfield = topic.subfield
                    """

                    try:
                        session.run(query, topics=batch)
                        pbar.update(len(batch))
                    except Exception as e:
                        log.error(f"Error creating topic nodes batch: {e}")
                        pbar.update(len(batch))

        # Create HAS_TOPIC relationships
        log.info("Creating HAS_TOPIC relationships...")
        topic_relationships = []
        for paper in papers:
            paper_id = paper["id"]
            for topic in paper.get("topics", []):
                topic_relationships.append({
                    "paper_id": paper_id,
                    "topic_id": topic["id"],
                    "score": topic["score"]
                })

        with self.driver.session(database=self.database) as session:
            with tqdm(total=len(topic_relationships), desc="Creating HAS_TOPIC relationships") as pbar:
                for i in range(0, len(topic_relationships), TOPIC_BATCH_SIZE):
                    batch = topic_relationships[i:i + TOPIC_BATCH_SIZE]

                    query = """
                    UNWIND $relationships AS rel
                    MATCH (p:Paper {id: rel.paper_id})
                    MATCH (t:Topic {id: rel.topic_id})
                    MERGE (p)-[:HAS_TOPIC {score: rel.score}]->(t)
                    """

                    try:
                        session.run(query, relationships=batch)
                        pbar.update(len(batch))
                    except Exception as e:
                        log.error(f"Error creating HAS_TOPIC relationships batch: {e}")
                        pbar.update(len(batch))

    def create_citation_edges(self, papers: List[Dict]) -> None:
        """
        Create citation edges between papers in batches.

        Args:
            papers: List of processed papers with reference information
        """
        log.info("Creating citation edges...")

        # Build citation relationships
        citations = []
        for paper in papers:
            paper_id = paper["id"]
            for ref_id in paper["references"]:
                if ref_id != paper_id:  # Avoid self-citations
                    citations.append({"citing": paper_id, "cited": ref_id})

        log.info(f"Creating {len(citations)} citation edges...")

        with self.driver.session(database=self.database) as session:
            with tqdm(total=len(citations), desc="Creating citation edges") as pbar:
                for i in range(0, len(citations), CITATION_BATCH_SIZE):
                    batch = citations[i:i + CITATION_BATCH_SIZE]

                    query = """
                    UNWIND $citations AS citation
                    MATCH (citing:Paper {id: citation.citing})
                    MATCH (cited:Paper {id: citation.cited})
                    MERGE (citing)-[:CITES]->(cited)
                    """

                    try:
                        session.run(query, citations=batch)
                        pbar.update(len(batch))

                        if (i + len(batch)) % 10000 == 0:
                            log.info(f"Created {i + len(batch)} citation edges...")

                    except Exception as e:
                        log.error(f"Error creating citation edges batch: {e}")
                        pbar.update(len(batch))

    def get_graph_statistics(self) -> Dict[str, int]:
        """
        Retrieve basic graph statistics.

        Returns:
            Dictionary with graph statistics
        """
        with self.driver.session(database=self.database) as session:
            stats = {}

            # Count papers
            result = session.run("MATCH (p:Paper) RETURN count(p) as count").single()
            stats["papers"] = result["count"] if result else 0

            # Count citations
            result = session.run("MATCH ()-[r:CITES]->() RETURN count(r) as count").single()
            stats["citations"] = result["count"] if result else 0

            # # Count papers by year
            # result = session.run("""
            #     MATCH (p:Paper)
            #     WHERE p.year IS NOT NULL
            #     RETURN p.year as year, count(p) as count
            #     ORDER BY year DESC LIMIT 10
            # """).data()
            # stats["papers_by_year"] = result

            # # Count by OA status
            # result = session.run("""
            #     MATCH (p:Paper)
            #     WHERE p.oa_status IS NOT NULL
            #     RETURN p.oa_status as status, count(p) as count
            #     ORDER BY count DESC
            # """).data()
            # stats["papers_by_oa_status"] = result

        return stats

    def build_graph(self, max_papers: int = MAX_PAPERS) -> Dict[str, int]:
        """
        Build the complete citation graph.

        Args:
            max_papers: Maximum number of papers to process

        Returns:
            Graph statistics
        """
        start_time = time.time()
        log.info("Starting citation graph build...")

        # Step 1: Create schema constraints
        self.create_schema_constraints()

        # Step 2: Fetch papers from OpenAlex
        papers = self.fetch_nlp_papers(max_papers)
        log.info(f"Fetched {len(papers)} papers")

        if not papers:
            log.warning("No papers fetched. Exiting.")
            return {"papers": 0, "citations": 0}

        # Step 3: Create paper nodes
        processed_papers = self.create_paper_nodes(papers)
        log.info(f"Created {len(processed_papers)} paper nodes")

        # Step 4: Create author nodes and AUTHORED relationships
        self.create_author_nodes_and_relationships(processed_papers)

        # Step 5: Create topic nodes and HAS_TOPIC relationships
        self.create_topic_nodes_and_relationships(processed_papers)

        # Step 6: Create citation edges
        self.create_citation_edges(processed_papers)

        # Step 7: Get statistics
        stats = self.get_graph_statistics()

        end_time = time.time()
        duration = end_time - start_time

        log.info(f"\nGraph build completed in {duration:.2f} seconds!")
        log.info(f"Final Statistics:")
        log.info(f"- Papers: {stats['papers']}")
        log.info(f"- Citations: {stats['citations']}")

        return stats

    def close(self) -> None:
        """Close the Neo4j driver connection."""
        if self.driver:
            self.driver.close()
            log.info("Closed Neo4j connection")


def main():
    """
    Main function to build the citation graph.
    """
    # Print configuration
    log.info("=== Citation Graph Builder ===")
    log.info(f"Neo4j URI: {NEO4J_URI}")
    log.info(f"Database: {NEO4J_DATABASE}")
    log.info(f"Max Papers: {MAX_PAPERS}")
    log.info(f"NLP Topics: {len(NLP_TOPICS)}")
    log.info(f"OA Statuses: {', '.join(OA_STATUSES)}")
    log.info("=" * 40)

    # Create graph builder
    builder = CitationGraphBuilder(
        uri=NEO4J_URI,
        user=NEO4J_USER,
        password=NEO4J_PASSWORD,
        database=NEO4J_DATABASE
    )

    try:
        # Build the graph
        stats = builder.build_graph(MAX_PAPERS)

        # Print final statistics
        print("\n" + "=" * 50)
        print("GRAPH STATISTICS")
        print("=" * 50)
        print(f"Total Papers: {stats['papers']:,}")
        print(f"Total Citations: {stats['citations']:,}")

        # if stats['papers_by_year']:
        #     print("\nPapers by Year (Top 10):")
        #     for year_data in stats['papers_by_year']:
        #         print(f"   {year_data['year']}: {year_data['count']:,}")

        # if stats['papers_by_oa_status']:
        #     print("\nPapers by OA Status:")
        #     for status_data in stats['papers_by_oa_status']:
        #         print(f"   {status_data['status']}: {status_data['count']:,}")

        # print("=" * 50)

    except KeyboardInterrupt:
        log.info("Graph build interrupted by user")
    except Exception as e:
        log.error(f"Graph build failed: {e}")
        raise
    finally:
        # Clean up
        builder.close()


if __name__ == "__main__":
    main()