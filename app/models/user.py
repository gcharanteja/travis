from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, EmailStr, constr
from datetime import datetime
import uuid

from app.utils.helpers import get_current_time_ist

class UserPreferences(BaseModel):
    """User preferences for application settings"""
    language: str = "en"
    notification_email: bool = True
    notification_push: bool = True
    notification_sms: bool = False
    dashboard_widgets: List[str] = ["account_summary", "recent_transactions", "goals", "investments"]
    theme: str = "light"
    currency_display: str = "INR"

class UserAddress(BaseModel):
    """User address information"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    line1: str
    line2: Optional[str] = None
    city: str
    state: str
    country: str = "India"
    pincode: str
    address_type: str = "home"  # home, work, other

class KycStatus(BaseModel):
    """KYC verification status"""
    pan_verified: bool = False
    aadhaar_verified: bool = False
    email_verified: bool = False
    phone_verified: bool = False
    address_verified: bool = False
    document_verified: bool = False
    last_verified: Optional[datetime] = None
    verification_notes: Optional[str] = None

class User(BaseModel):
    """
    User model representing a registered user of the application
    
    This is the core user model referenced by all other models
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    email: EmailStr
    phone: Optional[str] = None
    full_name: str
    date_of_birth: Optional[datetime] = None
    
    # Authentication
    password_hash: str
    password_salt: str
    is_active: bool = True
    last_login: Optional[datetime] = None
    failed_login_attempts: int = 0
    
    # Profile
    profile_picture_url: Optional[str] = None
    addresses: List[UserAddress] = []
    occupation: Optional[str] = None
    income_range: Optional[str] = None  # e.g., "0-5L", "5-10L", "10-25L", "25L+"
    
    # KYC and verification
    pan_number: Optional[str] = None
    aadhaar_number: Optional[str] = None
    kyc_status: KycStatus = KycStatus()
    
    # Preferences and settings
    preferences: UserPreferences = UserPreferences()
    
    # Roles and permissions
    roles: List[str] = ["user"]  # user, admin, advisor
    permissions: List[str] = []
    
    # Metadata
    created_at: datetime = Field(default_factory=get_current_time_ist)
    updated_at: datetime = Field(default_factory=get_current_time_ist)
    last_active: datetime = Field(default_factory=get_current_time_ist)
    
    # Relationships (stored as references for MongoDB)
    account_ids: List[str] = []
    goal_ids: List[str] = []
    portfolio_ids: List[str] = []
    
    # Analytics and engagement
    risk_profile: Optional[str] = None  # conservative, moderate, aggressive
    financial_health_score: Optional[float] = None
    engagement_score: Optional[float] = None
    
    # App usage
    app_version: Optional[str] = None
    device_info: Optional[Dict[str, Any]] = None
    notification_tokens: List[str] = []
    
    class Config:
        json_schema_extra = {
            "example": {
                "email": "user@example.com",
                "phone": "+919876543210",
                "full_name": "Rahul Sharma",
                "date_of_birth": "1985-07-15T00:00:00",
                "password_hash": "5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8",
                "password_salt": "randomsaltvalue",
                "pan_number": "ABCDE1234F",
                "addresses": [
                    {
                        "line1": "123 Main Street",
                        "city": "Mumbai",
                        "state": "Maharashtra",
                        "pincode": "400001"
                    }
                ],
                "income_range": "5-10L"
            }
        }