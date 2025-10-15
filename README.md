# Paper Navigation

A semantic navigation system for academic papers built with Neo4j and FastAPI. This system allows you to explore paper networks, author collaborations, and research topics through a graph database.

## Architecture

The project consists of several components:

- **Neo4j Database**: Stores the paper graph with nodes (papers, authors, topics) and relationships
- **Graph Builder**: Fetches data from OpenAlex and builds the semantic graph
- **REST API**: Provides endpoints for paper navigation and exploration
- **LLM Integration**: Enables semantic search and retrieval capabilities

## Prerequisites

- Docker and Docker Compose
- Python 3.8+
- Neo4j Browser (for database visualization)

## Quick Start

### 1. Start Neo4j Database

```bash
# Navigate to the project root
cd /path/to/semantic_navigation

# Start Neo4j using Docker Compose
docker-compose -f docker/docker-compose.yml up -d

# Verify Neo4j is running
docker-compose -f docker/docker-compose.yml ps
```

Neo4j will be available at:
- Browser: http://localhost:7474
- Bolt connection: bolt://localhost:7687
- Username: neo4j
- Password: neo4j123

### 2. Build the Paper Graph

```bash
# Navigate to the semantic link builder
cd core/semantic_link

# Install Python dependencies
pip install requests tqdm neo4j

# Run the graph builder
python build_graph.py
```

This will:
- Fetch NLP-related papers from OpenAlex
- Create nodes for papers, authors, topics, concepts, etc.
- Build relationships between entities
- Create co-authorship networks
- Generate collaboration statistics

### 3. Start the API Server

```bash
# Navigate to the API folder
cd core/api

# Install API dependencies
pip install -r requirements.txt

# Start the API server
python main.py
```

The API will be available at:
- API endpoints: http://localhost:8000
- Interactive docs: http://localhost:8000/docs
- Alternative docs: http://localhost:8000/redoc

## Core Components

### Database Setup

The Neo4j database is configured in `docker/docker-compose.yml` with:
- Persistent data storage
- APOC and Graph Data Science plugins
- Optimized memory settings
- Health checks

### Graph Builder (`core/semantic_link/build_graph.py`)

The graph builder:
- Fetches papers from OpenAlex API
- Creates a comprehensive graph with:
  - Papers with metadata
  - Authors and their affiliations
  - Topics and concepts
  - Citations and references
  - Co-authorship networks
- Generates collaboration statistics

### REST API (`core/api/`)

The API provides endpoints for:
- Paper navigation: `/api/v1/navigation/paper/{paper_id}`
- Graph exploration: `/api/v1/navigation/graph/{graph_id}`
- System information: `/info`
- Health checks: `/health`

## Usage Examples

### Exploring Papers via API

```bash
# Get a paper and its connections
curl "http://localhost:8000/api/v1/navigation/paper/W587963984"

# Get a subgraph for visualization
curl "http://localhost:8000/api/v1/navigation/graph/W587963984"

# Get database statistics
curl "http://localhost:8000/info"
```

### Exploring in Neo4j Browser

1. Open http://localhost:7474 in your browser
2. Login with neo4j/neo4j123
3. Try these queries:

```cypher
// Find papers by topic
MATCH (p:Paper)-[:HAS_TOPIC]->(t:Topic {name: "Natural Language Processing Techniques"})
RETURN p.title, p.year LIMIT 10

// Find author collaboration networks
MATCH (a1:Author)-[:CO_AUTHORED_WITH]-(a2:Author)
RETURN a1.name, a2.name LIMIT 20

// Find most cited papers
MATCH (p:Paper)
RETURN p.title, p.cited_by_count
ORDER BY p.cited_by_count DESC LIMIT 10
```

## Configuration

### Environment Variables

For the API, you can set these environment variables:

```bash
export API_HOST=0.0.0.0
export API_PORT=8000
export API_DEBUG=false
```

### Graph Builder Configuration

In `core/semantic_link/build_graph.py`, you can modify:
- `MAX_PAPERS`: Number of papers to fetch (default: 1000)
- `NLP_TOPICS`: Topics to filter papers
- Neo4j connection settings

## Troubleshooting

### Common Issues

1. **Neo4j connection failed**:
   - Ensure Docker is running
   - Check if Neo4j container is up: `docker-compose -f docker/docker-compose.yml ps`
   - Verify ports 7474 and 7687 are available

2. **API import errors**:
   - Install all requirements: `pip install -r core/api/requirements.txt`
   - Ensure Neo4j is running before starting the API

3. **Graph builder errors**:
   - Check internet connection for OpenAlex API access
   - Reduce `MAX_PAPERS` if memory issues occur
   - Verify Neo4j credentials

### Logs and Monitoring

- Neo4j logs: `docker-compose -f docker/docker-compose.yml logs neo4j`
- API logs: Check console output when running `python core/api/main.py`
- Graph builder progress: Printed to console during execution

## Development

### Adding New Endpoints

1. Create new endpoint functions in `core/api/v1/paper_navigation.py`
2. Import and register them in `core/api/main.py`
3. Test with the interactive docs at http://localhost:8000/docs

### Extending the Graph

1. Modify `core/semantic_link/build_graph.py` to add new node types or relationships
2. Update constraints in the `create_constraints` function
3. Re-run the graph builder to populate new data

### Database Schema

The graph includes these node types:
- `Paper`: Academic papers with metadata
- `Author`: Paper authors with affiliations
- `Topic`: Research topics
- `Concept`: Academic concepts
- `Keyword`: Paper keywords
- `Institution`: Author affiliations

And these relationships:
- `AUTHORED`: Author wrote a paper
- `CO_AUTHORED_WITH`: Authors collaborated
- `CITES`: Paper cites another paper
- `RELATED_TO`: Semantically related papers
- `HAS_TOPIC`: Paper has a topic
- `HAS_CONCEPT`: Paper has a concept
- `AFFILIATED_WITH`: Author affiliated with institution