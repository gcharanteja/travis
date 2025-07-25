from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Union

import jwt
from passlib.context import CryptContext
from fastapi import HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.config.settings import get_settings
from app.utils.helpers import hash_password

# Get settings
settings = get_settings()

# Password context for hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 scheme for token authentication
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")

def verify_password(plain_password: str, hashed_password: str, salt: str) -> bool:
    """
    Verify that a password matches the hashed version
    """
    password_dict = hash_password(plain_password, salt)
    return password_dict["hash"] == hashed_password

def get_password_hash(password: str) -> Dict[str, str]:
    """
    Create a hashed password with salt
    """
    return hash_password(password)

def create_access_token(subject: Union[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token
    """
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
    
    to_encode = {"exp": expire, "sub": str(subject)}
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

def decode_access_token(token: str) -> Dict[str, Any]:
    """
    Decode a JWT access token
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

def encrypt_sensitive_data(data: str) -> str:
    """
    Encrypt sensitive data using a symmetric encryption
    
    Note: In production, consider using a more robust encryption method
    like Fernet from cryptography library
    """
    # Simple base64 encoding for demonstration - replace with proper encryption in production
    import base64
    return base64.b64encode(data.encode()).decode()

def decrypt_sensitive_data(encrypted_data: str) -> str:
    """
    Decrypt sensitive data
    """
    # Simple base64 decoding for demonstration - replace with proper decryption in production
    import base64
    return base64.b64decode(encrypted_data.encode()).decode()

def create_api_key() -> str:
    """
    Generate a secure API key for integrations
    """
    import secrets
    return secrets.token_urlsafe(32)

async def get_current_user(token: str = None) -> Dict[str, Any]:
    """
    Get current user from JWT token
    
    Note: This is a placeholder. The actual implementation should
    fetch the user from the database using the user_id from the token.
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    payload = decode_access_token(token)
    user_id: str = payload.get("sub")
    
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # In a real implementation, you would fetch the user from the database here
    # For example: user = await get_user_by_id(user_id)
    # For now, we'll just return the user_id
    return {"id": user_id}

def validate_admin_access(user: Dict[str, Any]) -> bool:
    """
    Validate if a user has admin access
    
    Note: This is a placeholder. The actual implementation should
    check the user's roles or permissions in the database.
    """
    # In a real implementation, you would check if the user has admin role
    # For example: return "admin" in user.get("roles", [])
    # For now, we'll just return False
    return False