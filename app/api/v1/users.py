import os
import uuid
import shutil
from typing import List, Optional, Dict, Any
from bson import ObjectId
from jwt import decode, PyJWTError

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Query
from fastapi.responses import JSONResponse
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config.database import get_collection, get_database
from app.config.settings import get_settings
from app.core.security import oauth2_scheme
from app.core.exceptions import UnauthorizedException, NotFoundException, BadRequestException, ValidationException
from app.schemas.user import (
    UserResponse, UserUpdate, AddressCreate, AddressUpdate, 
    UserWithRelations, UserSummaryResponse
)
from app.utils.helpers import get_current_time_ist, ensure_directory_exists, convert_mongo_document
from app.utils.validators import validate_pan_card, validate_indian_phone, validate_pincode

settings = get_settings()

# Get the current user from JWT token
async def get_current_user(token: str = Depends(oauth2_scheme)) -> Dict[str, Any]:
    """
    Get the current authenticated user.
    """
    try:
        # Decode token
        payload = decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = payload.get("sub")
        
        if not user_id:
            raise UnauthorizedException(detail="Invalid token")
        
        # Get user from database - try with both string ID and ObjectId
        users_collection = await get_collection("users")
        
        # First try with string ID
        user = await users_collection.find_one({"_id": user_id})
        
        # If not found, try with ObjectId
        if not user:
            try:
                user = await users_collection.find_one({"_id": ObjectId(user_id)})
            except:
                pass
        
        if not user:
            raise NotFoundException(detail="User not found")
        
        # Update last active time
        current_time = get_current_time_ist()
        await users_collection.update_one(
            {"_id": user["_id"]},
            {"$set": {"last_active": current_time}}
        )
        
        # Convert MongoDB document to API format
        from app.utils.helpers import convert_mongo_document
        return convert_mongo_document(user)
    except PyJWTError:
        raise UnauthorizedException(detail="Invalid or expired token")
    # Add this debug code temporarily at the beginning of get_current_user
    import jwt
    import base64
    import json

    token_parts = token.split('.')
    if len(token_parts) >= 2:
        payload_bytes = base64.urlsafe_b64decode(token_parts[1] + '=' * (4 - len(token_parts[1]) % 4))
        print(f"Token payload: {json.loads(payload_bytes)}")

router = APIRouter(
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(get_current_user)],  # All routes require authentication
    responses={
        401: {"description": "Unauthorized"},
        404: {"description": "Not found"},
        403: {"description": "Forbidden"},
    },
)

@router.get("/profile", response_model=UserWithRelations)
async def get_profile(current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    Get the current user's profile with related entity counts.
    """
    # Get counts of related entities
    db = await get_database()
    
    # Convert string id back to ObjectId for MongoDB queries
    try:
        user_id_for_query = ObjectId(current_user["id"])
    except:
        user_id_for_query = current_user["id"]
    
    # Get accounts count
    accounts_count = await db.accounts.count_documents({"user_id": user_id_for_query})
    
    # Get goals count
    goals_count = await db.goals.count_documents({"user_id": user_id_for_query})
    
    # Get portfolios count
    portfolios_count = await db.portfolios.count_documents({"user_id": user_id_for_query})
    
    # Mask sensitive data
    if current_user.get("pan_number"):
        current_user["pan_number"] = current_user["pan_number"][:5] + "****" + current_user["pan_number"][-1]
    
    # Add counts to response
    current_user["account_count"] = accounts_count
    current_user["goal_count"] = goals_count
    current_user["portfolio_count"] = portfolios_count
    
    return current_user

@router.put("/profile", response_model=UserResponse)
async def update_profile(
    user_data: UserUpdate,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Update the current user's profile information.
    """
    users_collection = await get_collection("users")
    
    # Prepare update data
    update_data = {}
    if user_data.full_name is not None:
        update_data["full_name"] = user_data.full_name
    
    if user_data.phone is not None:
        if not validate_indian_phone(user_data.phone):
            raise ValidationException(detail="Invalid phone number format")
        update_data["phone"] = user_data.phone
    
    if user_data.date_of_birth is not None:
        update_data["date_of_birth"] = user_data.date_of_birth
    
    if user_data.occupation is not None:
        update_data["occupation"] = user_data.occupation
    
    if user_data.income_range is not None:
        update_data["income_range"] = user_data.income_range
    
    if user_data.pan_number is not None:
        if not validate_pan_card(user_data.pan_number):
            raise ValidationException(detail="Invalid PAN card format")
        update_data["pan_number"] = user_data.pan_number
        # Reset PAN verification status
        update_data["kyc_status.pan_verified"] = False
    
    if user_data.preferences is not None:
        update_data["preferences"] = user_data.preferences.dict()
    
    if user_data.profile_picture_url is not None:
        update_data["profile_picture_url"] = user_data.profile_picture_url
    
    # Set updated timestamp
    update_data["updated_at"] = get_current_time_ist()
    
    # Update user
    # Get user ID as ObjectId for queries
    try:
        user_id = ObjectId(current_user["id"])
    except:
        user_id = current_user["id"]
        
    if update_data:
        await users_collection.update_one(
            {"_id": user_id},
            {"$set": update_data}
        )
    
    # Get updated user
    updated_user = await users_collection.find_one({"_id": user_id})
    
    # Mask sensitive data
    if updated_user.get("pan_number"):
        updated_user["pan_number"] = updated_user["pan_number"][:5] + "****" + updated_user["pan_number"][-1]
    
    # Convert for response
    return convert_mongo_document(updated_user)

@router.post("/upload-avatar", response_model=Dict[str, str])
async def upload_avatar(
    file: UploadFile = File(...),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Upload a profile picture for the current user.
    """
    # Validate file type
    allowed_extensions = [".jpg", ".jpeg", ".png"]
    file_extension = os.path.splitext(file.filename)[1].lower()
    
    if file_extension not in allowed_extensions:
        raise BadRequestException(
            detail="Invalid file type. Allowed types: jpg, jpeg, png",
            code="invalid_file_type"
        )
    
    # Check file size (max 2MB)
    max_size = 2 * 1024 * 1024  # 2MB in bytes
    file_content = await file.read()
    await file.seek(0)  # Reset file pointer
    
    if len(file_content) > max_size:
        raise BadRequestException(
            detail="File size too large. Maximum size: 2MB",
            code="file_too_large"
        )
    
    # Create unique filename
    unique_filename = f"{current_user['_id']}_{uuid.uuid4()}{file_extension}"

    # Create directory if it doesn't exist
    upload_dir = "uploads/avatars"
    ensure_directory_exists(upload_dir)

    # Save file
    file_path = f"{upload_dir}/{unique_filename}"
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Save only the filename in DB
    users_collection = await get_collection("users")
    await users_collection.update_one(
        {"_id": current_user["_id"]},
        {
            "$set": {
                "profile_picture_url": unique_filename,
                "updated_at": get_current_time_ist()
            }
        }
    )

    # Return the filename (frontend will construct the full URL)
    return {"profile_picture_url": unique_filename}

@router.post("/addresses", status_code=status.HTTP_201_CREATED)
async def add_address(
    address: AddressCreate,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Add a new address to the user's profile.
    """
    # Validate pincode
    if not validate_pincode(address.pincode):
        raise ValidationException(detail="Invalid PIN code format")
    
    users_collection = await get_collection("users")
    
    # Add an ID to the address
    address_dict = address.dict()
    address_dict["id"] = str(uuid.uuid4())
    
    # Add address to user
    await users_collection.update_one(
        {"_id": ObjectId(current_user["id"])},
        {
            "$push": {"addresses": address_dict},
            "$set": {"updated_at": get_current_time_ist()}
        }
    )
    
    # Get updated user
    updated_user = await users_collection.find_one({"_id": ObjectId(current_user["id"])})
    
    # Return the newly added address (last in the list)
    return updated_user["addresses"][-1]

@router.put("/addresses/{address_id}")
async def update_address(
    address_id: str,
    address: AddressUpdate,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Update a user address by ID.
    """
    # Validate pincode if provided
    if address.pincode and not validate_pincode(address.pincode):
        raise ValidationException(detail="Invalid PIN code format")
    
    users_collection = await get_collection("users")
    
    # Try to convert string id back to ObjectId for MongoDB queries
    try:
        user_id = ObjectId(current_user["id"])
    except:
        user_id = current_user["id"]
    
    # Find the address index
    user = await users_collection.find_one({"_id": user_id})
    user_addresses = user.get("addresses", [])
    
    # Look for address by ID
    address_index = None
    for i, addr in enumerate(user_addresses):
        if addr.get("id") == address_id:
            address_index = i
            break
    
    if address_index is None:
        raise NotFoundException(detail=f"Address with ID {address_id} not found")
    
    # Update address fields
    update_fields = {}
    if address.line1 is not None:
        update_fields[f"addresses.{address_index}.line1"] = address.line1
    if address.line2 is not None:
        update_fields[f"addresses.{address_index}.line2"] = address.line2
    if address.city is not None:
        update_fields[f"addresses.{address_index}.city"] = address.city
    if address.state is not None:
        update_fields[f"addresses.{address_index}.state"] = address.state
    if address.country is not None:
        update_fields[f"addresses.{address_index}.country"] = address.country
    if address.pincode is not None:
        update_fields[f"addresses.{address_index}.pincode"] = address.pincode
    if address.address_type is not None:
        update_fields[f"addresses.{address_index}.address_type"] = address.address_type
    
    update_fields["updated_at"] = get_current_time_ist()
    
    # Update in database
    await users_collection.update_one(
        {"_id": user_id},
        {"$set": update_fields}
    )
    
    # Get updated user
    updated_user = await users_collection.find_one({"_id": user_id})
    
    # Return the updated address
    return updated_user["addresses"][address_index]

@router.delete("/addresses/{address_id}", status_code=status.HTTP_200_OK)
async def delete_address(
    address_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Delete a user address by ID.
    """
    # Try to convert string id back to ObjectId for MongoDB queries
    try:
        user_id = ObjectId(current_user["id"])
    except:
        user_id = current_user["id"]
        
    users_collection = await get_collection("users")
    
    # Get the full user document
    user = await users_collection.find_one({"_id": user_id})
    if not user:
        raise NotFoundException(detail="User not found")
    
    # Find the address
    user_addresses = user.get("addresses", [])
    address = None
    for addr in user_addresses:
        if addr.get("id") == address_id:
            address = addr
            break
    
    if not address:
        raise NotFoundException(detail=f"Address with ID {address_id} not found")
    
    # Remove address
    await users_collection.update_one(
        {"_id": user_id},
        {
            "$pull": {"addresses": {"id": address_id}},
            "$set": {"updated_at": get_current_time_ist()}
        }
    )
    
    return {"message": "Address deleted successfully"}

@router.delete("/addresses/{address_id}", status_code=status.HTTP_200_OK)
async def delete_address(
    address_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Delete a user address by ID.
    """
    users_collection = await get_collection("users")
    
    # Find the address
    user_addresses = current_user.get("addresses", [])
    address = next((addr for addr in user_addresses if addr.get("id") == address_id), None)
    
    if not address:
        raise NotFoundException(detail="Address not found")
    
    # Remove address
    await users_collection.update_one(
        {"_id": current_user["_id"]},
        {
            "$pull": {"addresses": {"id": address_id}},
            "$set": {"updated_at": get_current_time_ist()}
        }
    )
    
    return {"message": "Address deleted successfully"}

# Add other user-related endpoints below
# For example: update password, manage preferences, etc.

