from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import os
import uvicorn
from typing import Dict, List

# Import the router from v1
from v1.paper_navigation import router as paper_router, driver, run_query

# ===== CONFIG =====
API_VERSION = "v1"
API_PREFIX = f"/api/{API_VERSION}"
APP_TITLE = "Semantic Paper Navigation API"
APP_DESCRIPTION = """
API for navigating and exploring academic paper networks.
Provides endpoints for paper discovery, relationship exploration, and graph visualization.
"""

# ===== APP INITIALIZATION =====
app = FastAPI(
    title=APP_TITLE,
    description=APP_DESCRIPTION,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# ===== CORS CONFIGURATION =====
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify actual origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== INCLUDE ROUTERS =====
app.include_router(
    paper_router,
    prefix=f"{API_PREFIX}/navigation",
    tags=["Paper Navigation"]
)

# ===== ROOT ENDPOINTS =====
@app.get("/", tags=["Root"])
async def root():
    """
    Root endpoint providing basic API information
    """
    return {
        "message": "Welcome to Semantic Paper Navigation API",
        "version": "1.0.0",
        "api_prefix": API_PREFIX,
        "docs": "/docs",
        "redoc": "/redoc",
        "health": "/health"
    }


@app.get("/health", tags=["Health"])
async def health_check():
    """
    Health check endpoint to verify API is running
    """
    try:
        with driver.session(database="webofpapers") as session:
            result = session.run("RETURN 1 as test")
            test_value = result.single()["test"]

        if test_value == 1:
            return {
                "status": "healthy",
                "database": "connected",
                "api_version": "1.0.0"
            }
        else:
            raise HTTPException(status_code=503, detail="Database health check failed")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Service unavailable: {str(e)}")


@app.get("/info", tags=["System Information"])
async def system_info():
    """
    Get detailed system information including database statistics
    """
    try:
        stats = {}

        # Count different node types
        node_types = ["Paper", "Author", "Topic", "Concept", "Keyword", "Institution"]
        for node_type in node_types:
            result = run_query(f"MATCH (n:{node_type}) RETURN count(n) as count")
            stats[f"{node_type.lower()}_count"] = result[0]["count"] if result else 0

        # Count relationship types
        rel_types = ["CITES", "RELATED_TO", "AUTHORED", "CO_AUTHOR_WITH", "HAS_TOPIC", "HAS_CONCEPT"]
        for rel_type in rel_types:
            result = run_query(f"MATCH ()-[r:{rel_type}]-() RETURN count(r) as count")
            stats[f"{rel_type.lower()}_count"] = result[0]["count"] if result else 0

        return {
            "api_info": {
                "name": APP_TITLE,
                "version": "1.0.0",
                "description": APP_DESCRIPTION
            },
            "database_stats": stats,
            "endpoints": {
                "paper_navigation": f"{API_PREFIX}/navigation/paper/{{paper_id}}",
                "graph_exploration": f"{API_PREFIX}/navigation/graph/{{graph_id}}",
                "docs": "/docs"
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve system information: {str(e)}")


# ===== ERROR HANDLING =====
@app.exception_handler(404)
async def not_found_handler(request, exc):
    return JSONResponse(
        status_code=404,
        content={"error": "Resource not found", "detail": getattr(exc, "detail", str(exc))}
    )


@app.exception_handler(500)
async def internal_error_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)}
    )


# ===== MAIN EXECUTION =====
if __name__ == "__main__":
    # Get configuration from environment variables
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    debug = os.getenv("API_DEBUG", "false").lower() == "true"

    print(f"Starting {APP_TITLE} on {host}:{port}")
    print(f"API documentation available at http://{host}:{port}/docs")

    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=debug,
        log_level="info"
    )
