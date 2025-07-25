import os
from pydantic_settings import BaseSettings
from functools import lru_cache
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Settings(BaseSettings):
    # Application settings
    APP_NAME: str = "FinTech AI Platform"
    API_V1_STR: str = "/api/v1"
    DEBUG: bool = os.getenv("DEBUG", "False").lower() == "true"
    
    APP_FRONTEND_URL: str = os.getenv("APP_FRONTEND_URL", "http://localhost:3000")
    
    # Security
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-default-secret-key-change-in-production")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "800"))
    ALGORITHM: str = "HS256"
    
    # MongoDB Atlas settings
    MONGODB_URI: str = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    MONGODB_DB_NAME: str = os.getenv("MONGODB_DB_NAME", "fintech_ai_platform")
    
    # External APIs
    # Plaid API for bank integration
    PLAID_CLIENT_ID: str = os.getenv("PLAID_CLIENT_ID", "")
    PLAID_SECRET: str = os.getenv("PLAID_SECRET", "")
    PLAID_ENV: str = os.getenv("PLAID_ENV", "sandbox")  # sandbox, development, or production
    
    # LLM settings
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    AZURE_OPENAI_API_KEY: str = os.getenv("AZURE_OPENAI_API_KEY", "")
    AZURE_OPENAI_ENDPOINT: str = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    
    # Indian Market Data APIs
    NSE_INDIA_API_KEY: str = os.getenv("NSE_INDIA_API_KEY", "")
    BSE_INDIA_API_KEY: str = os.getenv("BSE_INDIA_API_KEY", "")

    # Feature flags
    ENABLE_AI_COACH: bool = os.getenv("ENABLE_AI_COACH", "True").lower() == "true"
    ENABLE_INVESTMENT_ASSISTANT: bool = os.getenv("ENABLE_INVESTMENT_ASSISTANT", "True").lower() == "true"
    ENABLE_BEHAVIORAL_ANALYSIS: bool = os.getenv("ENABLE_BEHAVIORAL_ANALYSIS", "True").lower() == "true"
    
    # Content settings
    MAX_EDUCATIONAL_CONTENT_ITEMS: int = int(os.getenv("MAX_EDUCATIONAL_CONTENT_ITEMS", "10"))
    
    class Config:
        case_sensitive = True
        env_file = ".env"

@lru_cache()
def get_settings():
    """a
    Create and cache an instance of the settings.
    This allows efficient reuse of settings throughout the application.
    """
    return Settings()