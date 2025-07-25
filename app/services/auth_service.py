import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Any, List, Tuple

from fastapi import HTTPException, status
from pydantic import EmailStr

from app.config.database import get_collection
from app.config.settings import get_settings
from app.core.exceptions import (
    UnauthorizedException, 
    BadRequestException, 
    NotFoundException,
    ForbiddenException
)
from app.core.security import (
    verify_password, 
    get_password_hash, 
    create_access_token,
    decode_access_token
)
from app.models.user import User, KycStatus, UserPreferences
from app.schemas.user import UserCreate, UserUpdate, PasswordChange
from app.utils.helpers import get_current_time_ist, mask_pan, mask_aadhaar
from app.utils.validators import validate_password_strength

# Get settings
settings = get_settings()

# Configure logger
logger = logging.getLogger(__name__)

async def register_user(user_data: UserCreate) -> Dict[str, Any]:
    """
    Register a new user in the system
    
    Args:
        user_data: User registration data
        
    Returns:
        Dictionary with user ID and email
        
    Raises:
        BadRequestException: If email already exists or validation fails
    """
    users_collection = await get_collection("users")
    
    # Check if email already exists
    existing_user = await users_collection.find_one({"email": user_data.email})
    if existing_user:
        raise BadRequestException(
            detail="Email already registered",
            code="email_exists"
        )
    
    # Validate password strength
    password_validation = validate_password_strength(user_data.password)
    if not password_validation["valid"]:
        raise BadRequestException(
            detail=password_validation["message"],
            code="weak_password"
        )
    
    # Hash the password
    password_dict = get_password_hash(user_data.password)
    
    # Create user model
    new_user = User(
        email=user_data.email,
        phone=user_data.phone,
        full_name=user_data.full_name,
        date_of_birth=user_data.date_of_birth,
        password_hash=password_dict["hash"],
        password_salt=password_dict["salt"],
        occupation=user_data.occupation,
        income_range=user_data.income_range,
        pan_number=user_data.pan_number,
        kyc_status=KycStatus(email_verified=False),
        preferences=user_data.preferences or UserPreferences()
    )
    
    if user_data.addresses:
        new_user.addresses = user_data.addresses
    
    # Insert user into database
    result = await users_collection.insert_one(new_user.dict())
    
    # Send verification email (to be implemented)
    # await send_verification_email(new_user.email, new_user.id)
    
    logger.info(f"User registered: {new_user.email}")
    
    return {
        "id": str(result.inserted_id),
        "email": new_user.email
    }

async def login_user(email: EmailStr, password: str) -> Dict[str, Any]:
    """
    Authenticate a user and generate access token
    
    Args:
        email: User email
        password: User password
        
    Returns:
        Dictionary with access token and user info
        
    Raises:
        UnauthorizedException: If authentication fails
    """
    users_collection = await get_collection("users")
    
    # Find user by email
    user = await users_collection.find_one({"email": email})
    if not user:
        raise UnauthorizedException(detail="Incorrect email or password")
    
    # Check if user is active
    if not user.get("is_active", True):
        raise UnauthorizedException(detail="Account is inactive")
    
    # Verify password
    if not verify_password(
        password, 
        user["password_hash"], 
        user["password_salt"]
    ):
        # Increment failed login attempts
        await users_collection.update_one(
            {"_id": user["_id"]},
            {"$inc": {"failed_login_attempts": 1}}
        )
        raise UnauthorizedException(detail="Incorrect email or password")
    
    # Reset failed login attempts and update last login
    await users_collection.update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "last_login": get_current_time_ist(),
                "failed_login_attempts": 0,
                "last_active": get_current_time_ist()
            }
        }
    )
    
    # Generate access token
    access_token = create_access_token(
        subject=str(user["_id"]),
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    
    print(f"Creating token for user ID: {str(user['_id'])}, type: {type(user['_id'])}")
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": str(user["_id"]),
        "email": user["email"],
        "full_name": user["full_name"],
        "roles": user.get("roles", ["user"]),
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60  # in seconds
    }

async def get_user_by_id(user_id: str) -> Dict[str, Any]:
    """
    Get user by ID
    
    Args:
        user_id: User ID
        
    Returns:
        User data
        
    Raises:
        NotFoundException: If user not found
    """
    users_collection = await get_collection("users")
    
    user = await users_collection.find_one({"_id": user_id})
    if not user:
        raise NotFoundException(detail="User not found")
    
    # Mask sensitive data
    if user.get("pan_number"):
        user["pan_number"] = mask_pan(user["pan_number"])
    
    if user.get("aadhaar_number"):
        user["aadhaar_number"] = mask_aadhaar(user["aadhaar_number"])
    
    return user

async def update_user(user_id: str, user_data: UserUpdate) -> Dict[str, Any]:
    """
    Update user profile information
    
    Args:
        user_id: User ID
        user_data: User data to update
        
    Returns:
        Updated user data
        
    Raises:
        NotFoundException: If user not found
    """
    users_collection = await get_collection("users")
    
    # Check if user exists
    existing_user = await users_collection.find_one({"_id": user_id})
    if not existing_user:
        raise NotFoundException(detail="User not found")
    
    # Prepare update data
    update_data = {k: v for k, v in user_data.dict(exclude_unset=True).items() if v is not None}
    
    if update_data:
        update_data["updated_at"] = get_current_time_ist()
        
        # Update user
        await users_collection.update_one(
            {"_id": user_id},
            {"$set": update_data}
        )
    
    # Get updated user
    updated_user = await users_collection.find_one({"_id": user_id})
    
    # Mask sensitive data
    if updated_user.get("pan_number"):
        updated_user["pan_number"] = mask_pan(updated_user["pan_number"])
    
    if updated_user.get("aadhaar_number"):
        updated_user["aadhaar_number"] = mask_aadhaar(updated_user["aadhaar_number"])
    
    return updated_user

async def change_password(user_id: str, password_data: PasswordChange) -> bool:
    """
    Change user password
    
    Args:
        user_id: User ID
        password_data: Current and new password
        
    Returns:
        True if successful
        
    Raises:
        UnauthorizedException: If current password is incorrect
        BadRequestException: If new password is invalid
    """
    users_collection = await get_collection("users")
    
    # Get user
    user = await users_collection.find_one({"_id": user_id})
    if not user:
        raise NotFoundException(detail="User not found")
    
    # Verify current password
    if not verify_password(
        password_data.current_password, 
        user["password_hash"], 
        user["password_salt"]
    ):
        raise UnauthorizedException(detail="Current password is incorrect")
    
    # Validate new password strength
    password_validation = validate_password_strength(password_data.new_password)
    if not password_validation["valid"]:
        raise BadRequestException(
            detail=password_validation["message"],
            code="weak_password"
        )
    
    # Hash the new password
    password_dict = get_password_hash(password_data.new_password)
    
    # Update password
    await users_collection.update_one(
        {"_id": user_id},
        {
            "$set": {
                "password_hash": password_dict["hash"],
                "password_salt": password_dict["salt"],
                "updated_at": get_current_time_ist()
            }
        }
    )
    
    logger.info(f"Password changed for user: {user_id}")
    
    return True

async def initiate_password_reset(email: EmailStr) -> bool:
    """
    Initiate password reset process
    
    Args:
        email: User email
        
    Returns:
        True if reset email sent
        
    Note: Always return true even if email not found for security
    """
    users_collection = await get_collection("users")
    
    # Check if user exists
    user = await users_collection.find_one({"email": email})
    if not user:
        # Log but don't reveal to caller
        logger.warning(f"Password reset requested for non-existent email: {email}")
        return True
    
    # Generate reset token
    reset_token = create_access_token(
        subject=f"reset_{str(user['_id'])}",
        expires_delta=timedelta(hours=1)
    )
    
    # Store reset token in database
    await users_collection.update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "reset_token": reset_token,
                "reset_token_expires": get_current_time_ist() + timedelta(hours=1)
            }
        }
    )
    
    # Send password reset email (to be implemented)
    # await send_password_reset_email(email, reset_token)
    
    logger.info(f"Password reset initiated for user: {email}")
    
    return True

async def complete_password_reset(reset_token: str, new_password: str) -> bool:
    """
    Complete password reset with token
    
    Args:
        reset_token: Password reset token
        new_password: New password
        
    Returns:
        True if successful
        
    Raises:
        UnauthorizedException: If token is invalid
        BadRequestException: If new password is invalid
    """
    try:
        # Decode token
        payload = decode_access_token(reset_token)
        if not payload.get("sub", "").startswith("reset_"):
            raise UnauthorizedException(detail="Invalid reset token")
        
        user_id = payload["sub"].replace("reset_", "")
        
        # Validate password
        password_validation = validate_password_strength(new_password)
        if not password_validation["valid"]:
            raise BadRequestException(
                detail=password_validation["message"],
                code="weak_password"
            )
        
        users_collection = await get_collection("users")
        
        # Get user
        user = await users_collection.find_one({
            "_id": user_id,
            "reset_token": reset_token,
            "reset_token_expires": {"$gt": get_current_time_ist()}
        })
        
        if not user:
            raise UnauthorizedException(detail="Invalid or expired reset token")
        
        # Hash new password
        password_dict = get_password_hash(new_password)
        
        # Update password and clear reset token
        await users_collection.update_one(
            {"_id": user_id},
            {
                "$set": {
                    "password_hash": password_dict["hash"],
                    "password_salt": password_dict["salt"],
                    "updated_at": get_current_time_ist()
                },
                "$unset": {
                    "reset_token": "",
                    "reset_token_expires": ""
                }
            }
        )
        
        logger.info(f"Password reset completed for user: {user_id}")
        
        return True
    except Exception as e:
        logger.error(f"Error in password reset: {str(e)}")
        raise UnauthorizedException(detail="Invalid reset token")

async def verify_email(verification_token: str) -> bool:
    """
    Verify user email with token
    
    Args:
        verification_token: Email verification token
        
    Returns:
        True if successful
        
    Raises:
        UnauthorizedException: If token is invalid
    """
    try:
        # Decode token
        payload = decode_access_token(verification_token)
        if not payload.get("sub", "").startswith("verify_"):
            raise UnauthorizedException(detail="Invalid verification token")
        
        user_id = payload["sub"].replace("verify_", "")
        
        users_collection = await get_collection("users")
        
        # Update user
        result = await users_collection.update_one(
            {"_id": user_id},
            {
                "$set": {
                    "kyc_status.email_verified": True,
                    "updated_at": get_current_time_ist()
                }
            }
        )
        
        if result.modified_count == 0:
            raise NotFoundException(detail="User not found")
        
        logger.info(f"Email verified for user: {user_id}")
        
        return True
    except Exception as e:
        logger.error(f"Error in email verification: {str(e)}")
        raise UnauthorizedException(detail="Invalid verification token")

async def check_permission(user_id: str, permission: str) -> bool:
    """
    Check if user has a specific permission
    
    Args:
        user_id: User ID
        permission: Permission to check
        
    Returns:
        True if user has permission, False otherwise
    """
    users_collection = await get_collection("users")
    
    user = await users_collection.find_one({"_id": user_id})
    if not user:
        return False
    
    # Admin role has all permissions
    if "admin" in user.get("roles", []):
        return True
    
    # Check specific permission
    return permission in user.get("permissions", [])

async def is_admin(user_id: str) -> bool:
    """
    Check if user has admin role
    
    Args:
        user_id: User ID
        
    Returns:
        True if user is admin, False otherwise
    """
    users_collection = await get_collection("users")
    
    user = await users_collection.find_one({"_id": user_id})
    if not user:
        return False
    
    return "admin" in user.get("roles", [])

async def validate_token(token: str) -> Dict[str, Any]:
    """
    Validate JWT token and return user data
    
    Args:
        token: JWT token
        
    Returns:
        User data
        
    Raises:
        UnauthorizedException: If token is invalid
    """
    try:
        # Decode token
        payload = decode_access_token(token)
        user_id = payload.get("sub")
        
        if not user_id:
            raise UnauthorizedException(detail="Invalid token")
        
        # Get user
        users_collection = await get_collection("users")
        user = await users_collection.find_one({"_id": user_id})
        
        if not user:
            raise UnauthorizedException(detail="User not found")
        
        if not user.get("is_active", True):
            raise UnauthorizedException(detail="User account is inactive")
        
        # Update last active time
        await users_collection.update_one(
            {"_id": user_id},
            {"$set": {"last_active": get_current_time_ist()}}
        )
        
        # Remove sensitive data
        if "password_hash" in user:
            del user["password_hash"]
        if "password_salt" in user:
            del user["password_salt"]
        
        # Mask PAN and Aadhaar
        if user.get("pan_number"):
            user["pan_number"] = mask_pan(user["pan_number"])
        if user.get("aadhaar_number"):
            user["aadhaar_number"] = mask_aadhaar(user["aadhaar_number"])
        
        return user
    except Exception as e:
        logger.error(f"Token validation error: {str(e)}")
        raise UnauthorizedException(detail="Invalid token")

async def update_kyc_status(user_id: str, kyc_updates: Dict[str, bool]) -> Dict[str, Any]:
    """
    Update KYC verification status for a user
    
    Args:
        user_id: User ID
        kyc_updates: Dictionary with KYC fields to update
        
    Returns:
        Updated KYC status
        
    Raises:
        NotFoundException: If user not found
    """
    users_collection = await get_collection("users")
    
    # Check if user exists
    user = await users_collection.find_one({"_id": user_id})
    if not user:
        raise NotFoundException(detail="User not found")
    
    # Prepare update data
    update_data = {}
    for field, value in kyc_updates.items():
        if field in [
            "pan_verified", "aadhaar_verified", "email_verified",
            "phone_verified", "address_verified", "document_verified"
        ]:
            update_data[f"kyc_status.{field}"] = value
    
    update_data["kyc_status.last_verified"] = get_current_time_ist()
    
    # Update user
    await users_collection.update_one(
        {"_id": user_id},
        {"$set": update_data}
    )
    
    # Get updated KYC status
    updated_user = await users_collection.find_one({"_id": user_id})
    
    return updated_user.get("kyc_status", {})