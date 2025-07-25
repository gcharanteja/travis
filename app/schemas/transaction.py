from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, validator
from datetime import datetime, date
from enum import Enum

from app.models.transaction import TransactionType, TransactionCategory, TransactionStatus


class MerchantBase(BaseModel):
    """Base schema for merchant information"""
    name: str
    category: Optional[str] = None
    logo_url: Optional[str] = None
    website: Optional[str] = None
    mcc_code: Optional[str] = None


class LocationBase(BaseModel):
    """Base schema for transaction location"""
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    postal_code: Optional[str] = None
    address: Optional[str] = None


class TransactionBase(BaseModel):
    """Base schema for transaction data"""
    amount: float
    transaction_type: TransactionType
    description: str
    date: datetime
    category: Optional[TransactionCategory] = None
    subcategory: Optional[str] = None
    tags: Optional[List[str]] = None
    
    @validator('amount')
    def validate_amount(cls, v):
        if not isinstance(v, (int, float)):
            raise ValueError('Amount must be a number')
        return v


class TransactionCreate(TransactionBase):
    """Schema for creating a new transaction"""
    user_id: str
    account_id: str
    original_description: Optional[str] = None
    merchant: Optional[MerchantBase] = None
    location: Optional[LocationBase] = None
    notes: Optional[str] = None
    is_manual: bool = True
    transfer_account_id: Optional[str] = None
    tax_relevant: Optional[bool] = False
    tax_category: Optional[str] = None


class TransactionUpdate(BaseModel):
    """Schema for updating transaction information"""
    description: Optional[str] = None
    amount: Optional[float] = None
    date: Optional[datetime] = None
    category: Optional[TransactionCategory] = None
    subcategory: Optional[str] = None
    tags: Optional[List[str]] = None
    notes: Optional[str] = None
    merchant: Optional[MerchantBase] = None
    tax_relevant: Optional[bool] = None
    tax_category: Optional[str] = None
    is_recurring: Optional[bool] = None
    is_subscription: Optional[bool] = None
    
    @validator('amount')
    def validate_amount(cls, v):
        if v is not None and not isinstance(v, (int, float)):
            raise ValueError('Amount must be a number')
        return v


class TransactionFilters(BaseModel):
    """Schema for filtering transactions"""
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    min_amount: Optional[float] = None
    max_amount: Optional[float] = None
    categories: Optional[List[TransactionCategory]] = None
    transaction_types: Optional[List[TransactionType]] = None
    search_query: Optional[str] = None
    tags: Optional[List[str]] = None
    is_recurring: Optional[bool] = None
    is_subscription: Optional[bool] = None
    merchant_names: Optional[List[str]] = None
    exclude_categories: Optional[List[TransactionCategory]] = None
    tax_relevant: Optional[bool] = None


class SplitTransactionItem(BaseModel):
    """Schema for a split transaction item"""
    amount: float
    description: str
    category: TransactionCategory
    subcategory: Optional[str] = None
    tags: Optional[List[str]] = None


class SplitTransactionRequest(BaseModel):
    """Schema for splitting a transaction"""
    transaction_id: str
    splits: List[SplitTransactionItem]
    
    @validator('splits')
    def validate_splits(cls, v, values):
        if not v or len(v) < 2:
            raise ValueError('At least 2 split items are required')
        return v


class TransactionResponse(TransactionBase):
    """Response schema for transaction data"""
    id: str
    transaction_id: str
    user_id: str
    account_id: str
    original_description: str
    status: TransactionStatus = TransactionStatus.COMPLETED
    notes: Optional[str] = None
    merchant: Optional[MerchantBase] = None
    location: Optional[LocationBase] = None
    posted_date: Optional[datetime] = None
    transfer_account_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    source: str = "plaid"
    is_manual: bool = False
    is_recurring: bool = False
    is_subscription: bool = False
    ai_categorized: bool = False
    ai_insights: Optional[str] = None
    tax_relevant: bool = False
    tax_category: Optional[str] = None
    is_split: bool = False
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "transaction_id": "TXN_20230528123456_a1b2c3d4",
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


class TransactionSummaryResponse(BaseModel):
    """Condensed transaction response for listings"""
    id: str
    transaction_id: str
    account_id: str
    amount: float
    transaction_type: TransactionType
    description: str
    date: datetime
    category: TransactionCategory
    merchant_name: Optional[str] = None
    status: TransactionStatus


class CategorySummary(BaseModel):
    """Summary of transactions by category"""
    category: TransactionCategory
    total_amount: float
    transaction_count: int
    percentage: float


class TransactionAnalytics(BaseModel):
    """Analytics data for transactions"""
    total_income: float = 0
    total_expenses: float = 0
    net_cashflow: float = 0
    top_spending_categories: List[CategorySummary] = []
    top_income_sources: List[CategorySummary] = []
    period_comparison: Dict[str, float] = {}
    recurring_expenses: float = 0
    subscription_expenses: float = 0