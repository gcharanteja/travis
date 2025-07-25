from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.routing import APIRoute
import logging

from app.api.v1 import auth, users, accounts, transactions, portfolios, goals , ai_coach , investments # Add goals import here
from app.core.middleware import setup_middleware
from app.config.database import connect_to_mongo, close_mongo_connection, health_check

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Fintech AI Platform",
    description="API for the Fintech AI Platform",
    version="0.1.0",
    debug=True 
)

# Mount the uploads directory for serving static files
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Set up middleware (CORS, rate limiting, etc.)
setup_middleware(app)

# Include routers with the correct API prefix
app.include_router(auth.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
app.include_router(accounts.router, prefix="/api/v1")
app.include_router(transactions.router, prefix="/api/v1")
app.include_router(portfolios.router, prefix="/api/v1")  # Add this line to include the portfolios router
app.include_router(goals.router, prefix="/api/v1")
app.include_router(ai_coach.router, prefix="/api/v1")  # Include AI Coach router
app.include_router(investments.router, prefix="/api/v1")  # Include Investments router

# Log registered routes
for route in app.routes:
    if isinstance(route, APIRoute):
        logger.debug(f"Registered route: {route.path}, methods: {route.methods}")
    else:
        logger.debug(f"Registered route: {route.path} (type: {type(route).__name__})")

# Startup and shutdown events
@app.on_event("startup")
async def startup_event():
    """Run tasks when the application starts"""
    logger.info("Starting application...")
    await connect_to_mongo()
    logger.info("Application started")

@app.on_event("shutdown")
async def shutdown_event():
    """Run tasks when the application shuts down"""
    logger.info("Shutting down application...")
    await close_mongo_connection()
    logger.info("Application shut down")

# Health check endpoint
@app.get("/health", tags=["health"])
async def get_health():
    """Health check endpoint"""
    db_healthy = await health_check()
    return {
        "status": "healthy" if db_healthy else "unhealthy",
        "database": "connected" if db_healthy else "disconnected"
    }

# Entry point for Render
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    reload = os.environ.get("ENV", "production") != "production"
    logger.info(f"Starting Uvicorn on port {port}, reload={reload}")
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=reload)