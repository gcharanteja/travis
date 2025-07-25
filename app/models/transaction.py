from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime
import uuid
from enum import Enum

from app.utils.helpers import get_current_time_ist, generate_transaction_id

class TransactionType(str, Enum):
    """Types of financial transactions"""
    DEBIT = "debit"
    CREDIT = "credit"
    TRANSFER = "transfer"
    FEE = "fee"
    INTEREST = "interest"
    ADJUSTMENT = "adjustment"
    OTHER = "other"

class TransactionCategory(str, Enum):
    """Main transaction categories"""
    FOOD_DINING = "food_dining"
    GROCERIES = "groceries"  # Add this line
    SHOPPING = "shopping"
    HOUSING = "housing"
    TRANSPORTATION = "transportation"
    ENTERTAINMENT = "entertainment"
    HEALTHCARE = "healthcare"
    EDUCATION = "education"
    PERSONAL_CARE = "personal_care"
    TRAVEL = "travel"
    BILLS_UTILITIES = "bills_utilities"
    INCOME = "income"
    INVESTMENTS = "investments"
    TRANSFER = "transfer"
    LOAN = "loan"
    INSURANCE = "insurance"
    TAX = "tax"
    GIFT = "gift"
    DONATION = "donation"
    OTHER = "other"
    UNKNOWN = "unknown"

class TransactionStatus(str, Enum):
    """Status of a transaction"""
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    REFUNDED = "refunded"
    
class MerchantInfo(BaseModel):
    """Information about the merchant/payee"""
    name: str
    category: Optional[str] = None
    logo_url: Optional[str] = None
    website: Optional[str] = None
    mcc_code: Optional[str] = None  # Merchant Category Code

class Location(BaseModel):
    """Geographic location of transaction"""
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    postal_code: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    address: Optional[str] = None

class Transaction(BaseModel):
    """
    Transaction model representing a financial transaction
    
    This includes debits, credits, transfers, and other account activities
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    transaction_id: str = Field(default_factory=generate_transaction_id)
    user_id: str
    account_id: str
    
    # Basic transaction details
    amount: float
    currency: str = "INR"
    transaction_type: TransactionType
    status: TransactionStatus = TransactionStatus.COMPLETED
    
    # Categorization
    category: TransactionCategory = TransactionCategory.UNKNOWN
    subcategory: Optional[str] = None
    tags: List[str] = []
    
    # Descriptive information
    description: str
    original_description: str  # Raw description from bank
    notes: Optional[str] = None
    
    # Merchant information
    merchant: Optional[MerchantInfo] = None
    
    # Date and time
    date: datetime
    posted_date: Optional[datetime] = None  # When it was posted/cleared
    
    # Location
    location: Optional[Location] = None
    
    # For transfers
    transfer_account_id: Optional[str] = None
    
    # Metadata
    created_at: datetime = Field(default_factory=get_current_time_ist)
    updated_at: datetime = Field(default_factory=get_current_time_ist)
    
    # Source and verification
    source: str = "plaid"  # plaid, manual, imported, etc.
    is_manual: bool = False
    is_recurring: bool = False
    is_subscription: bool = False
    
    # AI-enhanced data
    ai_categorized: bool = False
    ai_insights: Optional[str] = None
    spending_pattern_id: Optional[str] = None
    
    # For duplicate detection
    fingerprint: Optional[str] = None
    
    # Attachments (like receipts)
    attachments: List[str] = []
    
    # Tax related
    tax_relevant: bool = False
    tax_category: Optional[str] = None
    
    # Budget tracking
    budget_category_id: Optional[str] = None
    
    # Split transaction
    parent_transaction_id: Optional[str] = None
    is_split: bool = False
    split_parts: List[Dict[str, Any]] = []
    
    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "550e8400-e29b-41d4-a716-446655440000",
                "account_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
                "amount": 2500.00,
                "transaction_type": "debit",
                "category": "food_dining",
                "subcategory": "restaurants",
                "description": "Payment to Taj Restaurant",
                "original_description": "UPI/2023052812345678/PAYMENT/Taj Restaurant/UTIB0000001/user@ybl",
                "date": "2023-05-28T19:30:00",
                "merchant": {
                    "name": "Taj Restaurant"
                },
                "tags": ["dining", "weekend"]
            }
        }