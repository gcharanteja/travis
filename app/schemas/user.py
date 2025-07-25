from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, EmailStr, validator, constr
from datetime import datetime

from app.utils.validators import validate_pan_card, validate_indian_phone, validate_pincode


class UserAddressBase(BaseModel):
    """Base schema for user address"""
    line1: str
    line2: Optional[str] = None
    city: str
    state: str
    country: str = "India"
    pincode: str
    address_type: str = "home"  # home, work, other
    
    @validator('pincode')
    def validate_pin(cls, v):
        if not validate_pincode(v):
            raise ValueError('Invalid PIN code format')
        return v


class UserPreferencesBase(BaseModel):
    """Base schema for user preferences"""
    language: str = "en"
    notification_email: bool = True
    notification_push: bool = True
    notification_sms: bool = False
    dashboard_widgets: List[str] = ["account_summary", "recent_transactions", "goals", "investments"]
    theme: str = "light"
    currency_display: str = "INR"


class UserBase(BaseModel):
    """Base schema with common user attributes"""
    email: EmailStr
    phone: Optional[str] = None
    full_name: str
    
    @validator('phone')
    def validate_phone_number(cls, v):
        if v and not validate_indian_phone(v):
            raise ValueError('Invalid Indian phone number')
        return v


class UserCreate(UserBase):
    """Schema for creating a new user"""
    password: str = Field(..., min_length=8)
    date_of_birth: Optional[datetime] = None
    occupation: Optional[str] = None
    income_range: Optional[str] = None
    pan_number: Optional[str] = None
    addresses: Optional[List[UserAddressBase]] = []
    preferences: Optional[UserPreferencesBase] = None
    
    @validator('pan_number')
    def validate_pan(cls, v):
        if v and not validate_pan_card(v):
            raise ValueError('Invalid PAN card format')
        return v


class UserLogin(BaseModel):
    """Schema for user login"""
    email: EmailStr
    password: str


class UserUpdate(BaseModel):
    """Schema for updating user information (all fields optional)"""
    full_name: Optional[str] = None
    phone: Optional[str] = None
    date_of_birth: Optional[datetime] = None
    occupation: Optional[str] = None
    income_range: Optional[str] = None
    profile_picture_url: Optional[str] = None
    pan_number: Optional[str] = None
    preferences: Optional[UserPreferencesBase] = None
    
    @validator('phone')
    def validate_phone_number(cls, v):
        if v and not validate_indian_phone(v):
            raise ValueError('Invalid Indian phone number')
        return v
    
    @validator('pan_number')
    def validate_pan(cls, v):
        if v and not validate_pan_card(v):
            raise ValueError('Invalid PAN card format')
        return v


class AddressCreate(UserAddressBase):
    """Schema for adding a new address"""
    pass


class AddressUpdate(BaseModel):
    """Schema for updating an address"""
    line1: Optional[str] = None
    line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = "India"
    pincode: Optional[str] = None
    address_type: Optional[str] = None
    
    @validator('pincode')
    def validate_pin(cls, v):
        if v and not validate_pincode(v):
            raise ValueError('Invalid PIN code format')
        return v


class PasswordChange(BaseModel):
    """Schema for changing password"""
    current_password: str
    new_password: str = Field(min_length=8)


class KycStatusResponse(BaseModel):
    """Response schema for KYC status"""
    pan_verified: bool = False
    aadhaar_verified: bool = False
    email_verified: bool = False
    phone_verified: bool = False
    address_verified: bool = False
    document_verified: bool = False
    last_verified: Optional[datetime] = None
    verification_notes: Optional[str] = None


class UserResponse(UserBase):
    """Response schema for user data"""
    id: str
    date_of_birth: Optional[datetime] = None
    profile_picture_url: Optional[str] = None
    addresses: List[UserAddressBase] = []
    occupation: Optional[str] = None
    income_range: Optional[str] = None
    pan_number: Optional[str] = None  # Masked in the response
    kyc_status: KycStatusResponse
    preferences: UserPreferencesBase
    roles: List[str] = ["user"]
    created_at: datetime
    last_login: Optional[datetime] = None
    financial_health_score: Optional[float] = None
    risk_profile: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "email": "user@example.com",
                "phone": "+919876543210",
                "full_name": "Rahul Sharma",
                "date_of_birth": "1985-07-15T00:00:00",
                "occupation": "Software Engineer",
                "income_range": "5-10L",
                "pan_number": "ABCDE****F",
                "addresses": [
                    {
                        "line1": "123 Main Street",
                        "city": "Mumbai",
                        "state": "Maharashtra",
                        "pincode": "400001",
                        "address_type": "home"
                    }
                ],
                "kyc_status": {
                    "pan_verified": True,
                    "email_verified": True,
                    "phone_verified": True
                },
                "preferences": {
                    "language": "en",
                    "theme": "light"
                }
            }
        }


class UserSummaryResponse(BaseModel):
    """Condensed user response for listings and references"""
    id: str
    email: EmailStr
    full_name: str
    profile_picture_url: Optional[str] = None
    kyc_status: KycStatusResponse
    risk_profile: Optional[str] = None


class UserWithRelations(UserResponse):
    """User data with counts of related entities"""
    account_count: int = 0
    goal_count: int = 0
    portfolio_count: int = 0