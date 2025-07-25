from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, validator
from datetime import datetime
from enum import Enum

from app.utils.validators import validate_ifsc_code, validate_account_number
from app.models.account import AccountType, AccountStatus


class PlaidLinkRequest(BaseModel):
    """Request to create a Plaid Link token"""
    user_id: str


class PlaidLinkResponse(BaseModel):
    """Response with Plaid Link token"""
    link_token: str
    expiration: datetime


class PlaidExchangeRequest(BaseModel):
    """Request to exchange public token for access token"""
    public_token: str
    user_id: str


class AccountBase(BaseModel):
    """Base schema for account data"""
    account_name: str
    account_type: AccountType
    account_number_mask: str
    institution_name: str
    ifsc_code: Optional[str] = None
    
    @validator('ifsc_code')
    def validate_ifsc(cls, v):
        if v and not validate_ifsc_code(v):
            raise ValueError('Invalid IFSC code format')
        return v
    @validator('account_number_mask')
    def validate_account_number(v):
        if not validate_account_number(v):
            raise ValueError('Invalid account number format')
        return v


class AccountCreate(AccountBase):
    """Schema for manually creating a new account"""
    user_id: str
    current_balance: float = 0.0
    available_balance: Optional[float] = None
    limit: Optional[float] = None
    currency: str = "INR"
    account_subtype: Optional[str] = None
    integration_type: str = "manual"
    interest_rate: Optional[float] = None
    maturity_date: Optional[datetime] = None
    notes: Optional[str] = None
    
    @validator('current_balance', 'available_balance', 'limit')
    def validate_amount(cls, v):
        if v is not None and v < 0 and not isinstance(v, (int, float)):
            raise ValueError('Amount must be a number')
        return v


class AccountUpdate(BaseModel):
    """Schema for updating account information"""
    account_name: Optional[str] = None
    current_balance: Optional[float] = None
    available_balance: Optional[float] = None
    limit: Optional[float] = None
    status: Optional[AccountStatus] = None
    notes: Optional[str] = None
    interest_rate: Optional[float] = None
    maturity_date: Optional[datetime] = None
    custom_category: Optional[str] = None
    exclude_from_statistics: Optional[bool] = None
    display_order: Optional[int] = None
    
    @validator('current_balance', 'available_balance', 'limit')
    def validate_amount(cls, v):
        if v is not None and not isinstance(v, (int, float)):
            raise ValueError('Amount must be a number')
        return v


class PlaidMetadataResponse(BaseModel):
    """Response schema for Plaid account metadata"""
    institution_id: str
    institution_name: str
    last_updated: datetime
    status: str = "active"


class AccountResponse(AccountBase):
    """Response schema for account data"""
    id: str
    user_id: str
    institution_logo: Optional[str] = None
    institution_color: Optional[str] = None
    current_balance: float = 0.0
    available_balance: Optional[float] = None
    limit: Optional[float] = None
    currency: str = "INR"
    last_balance_update: datetime
    status: AccountStatus
    is_closed: bool = False
    integration_type: str
    plaid_metadata: Optional[PlaidMetadataResponse] = None
    account_subtype: Optional[str] = None
    interest_rate: Optional[float] = None
    maturity_date: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    custom_category: Optional[str] = None
    notes: Optional[str] = None
    exclude_from_statistics: bool = False
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
                "user_id": "550e8400-e29b-41d4-a716-446655440000",
                "account_name": "HDFC Salary Account",
                "account_type": "savings",
                "account_number_mask": "1234",
                "ifsc_code": "HDFC0001234",
                "institution_name": "HDFC Bank",
                "institution_logo": "https://example.com/logos/hdfc.png",
                "current_balance": 25000.50,
                "available_balance": 24500.50,
                "currency": "INR",
                "last_balance_update": "2023-06-01T10:30:00",
                "status": "active",
                "integration_type": "plaid"
            }
        }


class AccountSummaryResponse(BaseModel):
    """Condensed account response for listings and references"""
    id: str
    account_name: str
    account_type: AccountType
    institution_name: str
    institution_logo: Optional[str] = None
    current_balance: float
    currency: str = "INR"
    status: AccountStatus


class AccountsByTypeResponse(BaseModel):
    """Accounts grouped by type"""
    savings: List[AccountSummaryResponse] = []
    current: List[AccountSummaryResponse] = []
    credit_card: List[AccountSummaryResponse] = []
    loan: List[AccountSummaryResponse] = []
    investment: List[AccountSummaryResponse] = []
    other: List[AccountSummaryResponse] = []
    total_balance: float = 0.0
    

class RefreshAccountRequest(BaseModel):
    """Request to refresh account data"""
    account_id: str