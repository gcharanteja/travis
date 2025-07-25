#middleware.py
import time
import logging
from typing import Dict, Optional
from fastapi import FastAPI, Request, HTTPException, APIRouter
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

# Configure logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Settings
class Settings:
    DEBUG = True

def get_settings():
    return Settings()

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Simple request logging middleware"""
    
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        logger.info(f"{request.method} {request.url.path}")
        
        try:
            response = await call_next(request)
            process_time = time.time() - start_time
            logger.info(f"{request.method} {request.url.path} - {response.status_code} ({process_time:.3f}s)")
            return response
        except Exception as e:
            process_time = time.time() - start_time
            logger.error(f"{request.method} {request.url.path} - ERROR: {str(e)} ({process_time:.3f}s)")
            raise

def setup_middleware(app: FastAPI) -> None:
    """Set up simplified middleware"""

    # Add request logging
    app.add_middleware(RequestLoggingMiddleware)

    # Add CORS - Allow only trusted origins and credentials
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "https://localhost:3000",
            "http://127.0.0.1:3000",
            "https://127.0.0.1:3000",
            "https://kp9s49-8000.csb.app",
            "http://kp9s49-8000.csb.app"
        ],
        allow_credentials=True,  # <-- Allow credentials (cookies, auth headers)
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Initialize FastAPI app
app = FastAPI(title="Financial API", version="1.0.0")

# Apply settings and middleware
settings = get_settings()
setup_middleware(app)

# Router
router = APIRouter(prefix="/api/v1")



# Include router
app.include_router(router)

# Root endpoint
@app.get("/")
async def root():
    return {"message": "Financial API is running", "docs": "/docs"}