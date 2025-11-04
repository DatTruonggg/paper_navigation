# Paper Navigation

## Motivation

The Paper Navigation system was developed to address the challenge of searching and exploring academic papers in an intelligent and efficient manner. It will connect these papers together by implementing the cosine similarity on citation-based connection

This system enables:
- **Exploring paper networks** semantically rather than just keyword-based searching
- **Analyzing author collaborations** and research networks
- **Finding related topics** and academic concepts visually
- **Building knowledge graphs** from large academic datasets

## Architecture

The system is built on a microservices architecture with the following main components:

- **Neo4j Database**: Stores the paper graph with nodes (papers, authors, topics) and relationships
- **Graph Builder**: Fetches data from OpenAlex and builds the semantic graph
- **REST API**: Provides endpoints for paper navigation and exploration

## Quick Start
### 0. Module set up 

```cmd
pip install -r requirements.txt
```
### 1. Database Setup

#### Starting Neo4j Database
Please change the USERNAME and PASSWORD in dockercompse
```docker 
  neo4j:
    image: neo4j:5.14-community
    container_name: web-of-papers-neo4j
    restart: unless-stopped
    ports:
      - "7474:7474"  # HTTP
      - "7687:7687"  # Bolt
    environment:
      # Change these passwords in production!
      NEO4J_AUTH: username/password #TODO: Please change to your desired username/password
      NEO4J_dbms_default__database: database_name #TODO: Please change to your desired database name
      NEO4J_dbms_memory_heap_initial__size: 512m
      NEO4J_dbms_memory_heap_max__size: 2G
      NEO4J_dbms_memory_pagecache_size: 1G
      NEO4J_dbms_security_procedures_unrestricted: gds.*,apoc.*
      NEO4J_dbms_security_procedures_allowlist: gds.*,apoc.*
      # Enable APOC and GDS plugins
      NEO4J_PLUGINS: '["apoc", "graph-data-science"]'
    volumes:
      - neo4j_data:/data
      - neo4j_logs:/logs
      - neo4j_import:/var/lib/neo4j/import
      - neo4j_plugins:/plugins
    healthcheck:
      test: ["CMD", "cypher-shell", "-u", "user_name", "-p", "password", "RETURN 1"] #TODO : Change to your username/password
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 40s
```
```bash
# Navigate to the project root
cd semantic_navigation

# Start Neo4j using Docker Compose
docker-compose -f docker/docker-compose.yml up -d

# Verify Neo4j is running
docker-compose -f docker/docker-compose.yml ps
```

Neo4j will be available at:
- Browser: http://localhost:7474
- Bolt connection: bolt://localhost:7687
- Username: username
- Password: password

![alt text](/assets/neo4j_ui.png)

#### Database Configuration

The Neo4j database is configured in `docker/docker-compose.yml` with:
- Persistent data storage
- APOC and Graph Data Science plugins
- Optimized memory settings
- Health checks

### 2. Building the Paper Graph

#### Method: Graph Builder

```bash
# Navigate to the semantic link builder
cd core/graphs

# Run the graph builder
python graph_builder.py
```

This process will:
- **Fetch NLP-related papers** from OpenAlex API
- **Create nodes** for papers, authors, topics, concepts, etc.
- **Build relationships** between entities
- **Create co-authorship networks**
- **Generate collaboration statistics**

#### Method: Semantic Citation Graph

```bash
# Build semantic citation graph
cd core/graphs

# Run semantic citation builder
python semantic_citation.py
```

### 3. API Server Setup

```bash
# Navigate to the API folder
cd core/api

# Start the API server
python main.py
```

The API will be available at:
- API endpoints: http://localhost:8000
- Interactive docs: http://localhost:8000/docs
- Alternative docs: http://localhost:8000/redoc

![alt text](/assets/fastapi.png)

## Database Schema & Methods

### Node Types

- **`Paper`**: Academic papers with metadata
- **`Author`**: Paper authors with affiliations
- **`Topic`**: Research topics

### Relationship Types

- **`AUTHORED`**: Author wrote a paper
- **`CITES`**: Paper cites another paper
- **`HAS_TOPIC`**: Paper has a concept
- **`SIMILAR_TO`**: Bibliographic and co-citation

### Core Methods

#### Graph Building Methods

1. **Data Fetching**: 
   - Connect to OpenAlex API
   - Fetch papers by specified topics
   - Extract metadata and relationships

2. **Graph Construction**:
   - Create nodes with proper constraints
   - Build relationships between entities
   - Calculate collaboration statistics

3. **Semantic Analysis**:
   - Extract concepts and topics
   - Build semantic similarity relationships
   - Generate citation networks

#### API Methods

1. **Paper Navigation**:
   - `GET /api/v1/navigation/paper/{paper_id}`
   - Returns paper details and connections

2. **Graph Exploration**:
   - `GET /api/v1/navigation/graph/{graph_id}`
   - Returns subgraph for visualization

3. **System Information**:
   - `GET /info`
   - `GET /health`

## Usage Examples

### Exploring Papers via API

```bash
# Get a paper and its connections
curl "http://localhost:8000/api/v1/navigation/paper/W2752782242/similar"

# Get a subgraph for visualization
curl "http://localhost:8000/api/v1/navigation/graph/W2752782242"

# Get database statistics
curl "http://localhost:8000/info"

curl "http://localhost:8000/health"
```

### Exploring in Neo4j Browser

1. Open http://localhost:7474 in your browser
2. Login with username/password
3. Try these queries:

```cypher
// Find papers by topic
MATCH (p:Paper)-[:HAS_TOPIC]->(t:Topic {name: "Natural Language Processing Techniques"})
RETURN p.title, p.year LIMIT 10

// Find author and paper networks
MATCH p=()-[r:AUTHORED]->() RETURN p LIMIT 25

// Find most cited papers
MATCH (p:Paper)
RETURN p.title, p.cited_by_count
ORDER BY p.cited_by_count DESC LIMIT 10

// Find semantically papers
MATCH (p1:Paper {id: "W2752782242"})-[:SIMILAR_TO]-(p2:Paper)
RETURN p1.title, p2.title, p2.year LIMIT 10
```

## Configuration

### Environment Variables

```bash
export API_HOST=0.0.0.0
export API_PORT=8000
export API_DEBUG=false
```

### Graph Builder Configuration

In `core/graphs/graph_builder.py`, you can modify:
- `MAX_PAPERS`: Number of papers to fetch (default: 1000)
- `NLP_TOPICS`: Topics to filter papers
- Neo4j connection settings

## Development

### Adding New Endpoints

1. Create new endpoint functions in `core/api/v1/paper_navigation.py`
2. Import and register them in `core/api/main.py`
3. Test with the interactive docs at http://localhost:8000/docs

### Extending the Graph

1. Modify `core/graphs/graph_builder.py` to add new node types or relationships
2. Update constraints in the `create_constraints` function
3. Re-run the graph builder to populate new data

## Troubleshooting

### Common Issues

1. **Neo4j connection failed**:
   - Ensure Docker is running
   - Check if Neo4j container is up: `docker-compose -f docker/docker-compose.yml ps`
   - Verify ports 7474 and 7687 are available

2. **API import errors**:
   - Install all requirements: `pip install -r requirements.txt`
   - Ensure Neo4j is running before starting the API

3. **Graph builder errors**:
   - Check internet connection for OpenAlex API access
   - Reduce `MAX_PAPERS` if memory issues occur
   - Verify Neo4j credentials

### Logs and Monitoring
- Neo4j logs: `docker-compose -f docker/docker-compose.yml logs neo4j`
- API logs: Check console output when running `python core/api/main.py`
- Graph builder progress: Printed to console during execution