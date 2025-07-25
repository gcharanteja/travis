from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from bson import ObjectId

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Request
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer

from app.config.database import get_collection, get_database
from app.config.settings import get_settings
from app.schemas.user import UserCreate, UserLogin, UserResponse
from app.core.security import create_access_token, verify_password, get_password_hash, oauth2_scheme
from app.core.exceptions import UnauthorizedException, NotFoundException, BadRequestException, ValidationException
from app.utils.helpers import get_current_time_ist , convert_mongo_document
from app.utils.validators import validate_email

settings = get_settings()

router = APIRouter(
    prefix="/auth",
    tags=["authentication"],
    responses={
        404: {"description": "Not found"},
        401: {"description": "Unauthorized"},
        403: {"description": "Forbidden"},
    },
)

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(user_data: UserCreate):
    """
    Register a new user account.
    """
    # Get users collection
    users_collection = await get_collection("users")
    
    # Check if email already exists
    existing_user = await users_collection.find_one({"email": user_data.email})
    if existing_user:
        raise BadRequestException(
            detail="Email already registered",
            code="email_exists"
        )
    
    # Hash password
    password_dict = get_password_hash(user_data.password)
    
    # Prepare user document
    current_time = get_current_time_ist()
    new_user = {
        "email": user_data.email,
        "phone": user_data.phone,
        "full_name": user_data.full_name,
        "password_hash": password_dict["hash"],
        "password_salt": password_dict["salt"],
        "date_of_birth": user_data.date_of_birth,
        "occupation": user_data.occupation,
        "income_range": user_data.income_range,
        "pan_number": user_data.pan_number,
        "is_active": True,
        "roles": ["user"],
        "created_at": current_time,
        "updated_at": current_time,
        "last_active": current_time,
        "kyc_status": {
            "pan_verified": False,
            "aadhaar_verified": False,
            "email_verified": False,
            "phone_verified": False,
        }
    }
    
    # Add addresses if provided
    if user_data.addresses:
        new_user["addresses"] = [address.dict() for address in user_data.addresses]
    
    # Add preferences if provided
    if user_data.preferences:
        new_user["preferences"] = user_data.preferences.dict()
    else:
        # Default preferences
        new_user["preferences"] = {
            "language": "en",
            "notification_email": True,
            "notification_push": True,
            "notification_sms": False,
            "dashboard_widgets": ["account_summary", "recent_transactions", "goals", "investments"],
            "theme": "light",
            "currency_display": "INR"
        }
    
    # Insert user
    result = await users_collection.insert_one(new_user)
    
    # Get created user
    created_user = convert_mongo_document(await users_collection.find_one({"_id": result.inserted_id}))
    
    # Mask sensitive data
    if created_user.get("pan_number"):
        created_user["pan_number"] = created_user["pan_number"][:5] + "****" + created_user["pan_number"][-1]
    
    return created_user

@router.post("/login", response_model=Dict[str, Any])
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """
    Log in with username (email) and password to get access token.
    """
    # Get users collection
    users_collection = await get_collection("users")
    
    # Find user by email
    user = await users_collection.find_one({"email": form_data.username})
    if not user:
        raise UnauthorizedException(
            detail="Invalid email or password",
            code="invalid_credentials"
        )
    
    # Check if user is active
    if not user.get("is_active", True):
        raise UnauthorizedException(
            detail="User account is inactive",
            code="inactive_account"
        )
    
    # Verify password
    if not verify_password(form_data.password, user["password_hash"], user["password_salt"]):
        # Increment failed login attempts
        await users_collection.update_one(
            {"_id": user["_id"]},
            {"$inc": {"failed_login_attempts": 1}}
        )
        raise UnauthorizedException(
            detail="Invalid email or password",
            code="invalid_credentials"
        )
    
    # Reset failed login attempts and update last login
    current_time = get_current_time_ist()
    await users_collection.update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "failed_login_attempts": 0,
                "last_login": current_time,
                "last_active": current_time
            }
        }
    )
    
    # Create access token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        subject=user["_id"],
        expires_delta=access_token_expires
    )
    
    # Convert ObjectId to string
    user_id_str = str(user["_id"])
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 800,  # seconds
        "user_id": user_id_str,
        "email": user["email"],
        "full_name": user["full_name"]
    }

@router.post("/refresh", response_model=Dict[str, Any])
async def refresh_token(token: str = Depends(oauth2_scheme)):
    """
    Refresh the access token using an existing valid token.
    """
    from jwt import decode, PyJWTError
    
    try:
        # Decode token to get user ID
        payload = decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id_str = payload.get("sub")
        
        if not user_id_str:
            raise UnauthorizedException(detail="Invalid token")
        
        # Convert string user_id to ObjectId
        try:
            user_id = ObjectId(user_id_str)
        except:
            raise UnauthorizedException(detail="Invalid user ID in token")
        
        # Check if user exists and is active
        users_collection = await get_collection("users")
        user = await users_collection.find_one({"_id": user_id})
        
        if not user:
            raise NotFoundException(detail="User not found")
        
        if not user.get("is_active", True):
            raise UnauthorizedException(detail="User account is inactive")
        
        # Create new access token
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            subject=str(user["_id"]),
            expires_delta=access_token_expires
        )
        
        # Update last active time
        current_time = get_current_time_ist()
        await users_collection.update_one(
            {"_id": user["_id"]},
            {"$set": {"last_active": current_time}}
        )
        
        # Convert ObjectId to string for response
        user_id_str = str(user["_id"])
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,  # seconds
            "user_id": user_id_str,
            "email": user["email"],
            "full_name": user["full_name"]
        }
    except PyJWTError:
        raise UnauthorizedException(detail="Invalid or expired token")

@router.post("/forgot-password", status_code=status.HTTP_200_OK)
async def forgot_password(email_data: Dict[str, str], background_tasks: BackgroundTasks):
    """
    Initiate the password reset process by sending a password reset link.
    """
    # Extract email from request body
    email = email_data.get("email")
    if not email:
        raise ValidationException(detail="Email is required")
    
    # Validate email format
    if not validate_email(email):
        raise ValidationException(detail="Invalid email format")
    
    # Get users collection
    users_collection = await get_collection("users")
    
    # Check if user exists
    user = await users_collection.find_one({"email": email})
    
    # For security reasons, always return success even if email not found
    if not user:
        return {"message": "If your email exists in our system, you will receive a password reset link"}
    
    # Generate a password reset token (valid for 1 hour)
    reset_token_expires = timedelta(hours=1)
    reset_token = create_access_token(
        subject=f"reset_{str(user['_id'])}",
        expires_delta=reset_token_expires
    )
    
    # Store reset token in database
    current_time = get_current_time_ist()
    await users_collection.update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "reset_token": reset_token,
                "reset_token_expires": current_time + reset_token_expires,
                "updated_at": current_time
            }
        }
    )
    
    # Send password reset email (background task)
    # In a real implementation, you would have a proper email sending service
    # Here we just log the token
    frontend_url = getattr(settings, "APP_FRONTEND_URL", "http://localhost:3000")
    reset_link = f"{frontend_url}/reset-password?token={reset_token}"
    print(f"Password reset link for {email}: {reset_link}")
    
    return {"message": "If your email exists in our system, you will receive a password reset link"}

@router.post("/reset-password", status_code=status.HTTP_200_OK)
async def reset_password(reset_data: Dict[str, str]):
    """
    Reset the password using the token sent to the user's email.
    """
    from jwt import decode, PyJWTError
    from bson import ObjectId
    
    # Extract data from request body
    token = reset_data.get("token")
    new_password = reset_data.get("new_password")
    
    if not token or not new_password:
        raise ValidationException(detail="Token and new password are required")
    
    try:
        # Decode token
        payload = decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        reset_id = payload.get("sub")
        
        if not reset_id or not reset_id.startswith("reset_"):
            raise UnauthorizedException(detail="Invalid reset token")
        
        # Extract user ID from reset token
        user_id_str = reset_id.replace("reset_", "")
        
        try:
            user_id = ObjectId(user_id_str)
        except:
            raise UnauthorizedException(detail="Invalid user ID in token")
        
        # Get users collection
        users_collection = await get_collection("users")
        
        # Check if user exists and token is valid
        current_time = get_current_time_ist()
        user = await users_collection.find_one({
            "_id": user_id,
            "reset_token": token,
            "reset_token_expires": {"$gt": current_time}
        })
        
        if not user:
            raise UnauthorizedException(detail="Invalid or expired reset token")
        
        # Hash new password
        password_dict = get_password_hash(new_password)
        
        # Update password and remove reset token
        await users_collection.update_one(
            {"_id": user_id},
            {
                "$set": {
                    "password_hash": password_dict["hash"],
                    "password_salt": password_dict["salt"],
                    "updated_at": current_time
                },
                "$unset": {
                    "reset_token": "",
                    "reset_token_expires": ""
                }
            }
        )
        
        return {"message": "Password has been reset successfully"}
    except PyJWTError:
        raise UnauthorizedException(detail="Invalid or expired reset token")
