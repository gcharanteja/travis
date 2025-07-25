from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime
import uuid
from enum import Enum

from app.utils.helpers import get_current_time_ist

class AccountType(str, Enum):
    """Types of financial accounts"""
    SAVINGS = "savings"
    CURRENT = "current"
    CREDIT_CARD = "credit_card"
    LOAN = "loan"
    FIXED_DEPOSIT = "fixed_deposit"
    RECURRING_DEPOSIT = "recurring_deposit"
    PPF = "ppf"
    EPF = "epf"
    NPS = "nps"
    DEMAT = "demat"
    MUTUAL_FUND = "mutual_fund"
    CRYPTO = "crypto"
    CASH = "cash"
    OTHER = "other"

class AccountStatus(str, Enum):
    """Status of account connection"""
    ACTIVE = "active"
    PENDING = "pending"
    ERROR = "error"
    DISCONNECTED = "disconnected"
    DELETED = "deleted"

class PlaidAccountMetadata(BaseModel):
    """Metadata for accounts linked via Plaid"""
    access_token: str
    item_id: str
    institution_id: str
    institution_name: str
    last_updated: datetime = Field(default_factory=get_current_time_ist)
    status: str = "active"
    error_code: Optional[str] = None
    error_message: Optional[str] = None

class Account(BaseModel):
    """
    Account model representing a financial account linked to a user
    
    This includes bank accounts, credit cards, loans, investment accounts, etc.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    
    # Account details
    account_name: str  # Display name (e.g., "HDFC Savings")
    account_type: AccountType
    account_number_mask: str  # Last 4 digits of account number
    ifsc_code: Optional[str] = None  # For Indian bank accounts
    
    # Account provider details
    institution_name: str  # Bank or financial institution name
    institution_logo: Optional[str] = None
    institution_color: Optional[str] = None
    
    # Balance information
    current_balance: float = 0.0
    available_balance: Optional[float] = None
    limit: Optional[float] = None  # For credit cards and loans
    currency: str = "INR"
    last_balance_update: datetime = Field(default_factory=get_current_time_ist)
    
    # Account status
    status: AccountStatus = AccountStatus.ACTIVE
    is_closed: bool = False
    
    # Integration details
    integration_type: str  # "plaid", "manual", "direct_api", etc.
    plaid_metadata: Optional[PlaidAccountMetadata] = None
    
    # Manual refresh tracking
    last_refresh_attempt: Optional[datetime] = None
    refresh_error: Optional[str] = None
    refresh_status: str = "success"  # success, pending, failed
    
    # Account features
    supports_transactions: bool = True
    supports_balance: bool = True
    supports_details: bool = True
    
    # Metadata
    created_at: datetime = Field(default_factory=get_current_time_ist)
    updated_at: datetime = Field(default_factory=get_current_time_ist)
    
    # Additional information
    account_subtype: Optional[str] = None
    interest_rate: Optional[float] = None  # For interest-bearing accounts
    maturity_date: Optional[datetime] = None  # For FDs, RDs
    
    # User customization
    custom_category: Optional[str] = None
    notes: Optional[str] = None
    exclude_from_statistics: bool = False
    display_order: int = 0
    
    # Security and consent
    consent_expiry: Optional[datetime] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "550e8400-e29b-41d4-a716-446655440000",
                "account_name": "HDFC Salary Account",
                "account_type": "savings",
                "account_number_mask": "1234",
                "ifsc_code": "HDFC0001234",
                "institution_name": "HDFC Bank",
                "current_balance": 25000.50,
                "available_balance": 24500.50,
                "currency": "INR",
                "integration_type": "plaid"
            }
        }