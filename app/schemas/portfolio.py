from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, validator
from datetime import datetime
from enum import Enum

from app.models.portfolio import AssetClass, InvestmentType, RiskProfile


class HoldingBase(BaseModel):
    """Base schema for investment holding"""
    instrument_name: str
    instrument_type: InvestmentType
    units: float
    average_buy_price: float
    current_price: float
    asset_class: AssetClass
    
    @validator('units', 'average_buy_price', 'current_price')
    def validate_amount(cls, v):
        if not isinstance(v, (int, float)) or v < 0:
            raise ValueError('Amount must be a positive number')
        return v


class HoldingCreate(HoldingBase):
    """Schema for creating a new investment holding"""
    instrument_id: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    nav: Optional[float] = None
    scheme_code: Optional[str] = None
    folio_number: Optional[str] = None
    exchange: Optional[str] = None
    ticker: Optional[str] = None
    isin: Optional[str] = None
    
    @validator('nav')
    def validate_nav(cls, v):
        if v is not None and (not isinstance(v, (int, float)) or v <= 0):
            raise ValueError('NAV must be a positive number')
        return v


class HoldingUpdate(BaseModel):
    """Schema for updating investment holding"""
    units: Optional[float] = None
    average_buy_price: Optional[float] = None
    current_price: Optional[float] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    nav: Optional[float] = None
    
    @validator('units', 'average_buy_price', 'current_price', 'nav')
    def validate_amount(cls, v):
        if v is not None and (not isinstance(v, (int, float)) or v < 0):
            raise ValueError('Amount must be a positive number')
        return v


class AssetAllocationBase(BaseModel):
    """Base schema for asset allocation"""
    equity_percentage: float = 0.0
    debt_percentage: float = 0.0
    cash_percentage: float = 0.0
    real_estate_percentage: float = 0.0
    gold_percentage: float = 0.0
    alternative_percentage: float = 0.0
    crypto_percentage: float = 0.0
    
    @validator('equity_percentage', 'debt_percentage', 'cash_percentage', 
               'real_estate_percentage', 'gold_percentage', 'alternative_percentage', 
               'crypto_percentage')
    def validate_percentage(cls, v):
        if not isinstance(v, (int, float)) or v < 0 or v > 100:
            raise ValueError('Percentage must be between 0 and 100')
        return v


class PortfolioBase(BaseModel):
    """Base schema for portfolio data"""
    name: str
    description: Optional[str] = None
    portfolio_type: str = "custom"
    risk_profile: RiskProfile = RiskProfile.MODERATE


class PortfolioCreate(PortfolioBase):
    """Schema for creating a new portfolio"""
    user_id: str
    is_default: bool = False
    is_auto_rebalance: bool = False
    rebalance_frequency: Optional[str] = None
    goal_ids: Optional[List[str]] = None
    target_allocation: Optional[Dict[str, float]] = None
    
    @validator('target_allocation')
    def validate_target_allocation(cls, v):
        if v:
            total = sum(v.values())
            if not (99.0 <= total <= 101.0):  # Allow small rounding errors
                raise ValueError('Target allocation percentages must sum to 100%')
        return v


class PortfolioUpdate(BaseModel):
    """Schema for updating portfolio information"""
    name: Optional[str] = None
    description: Optional[str] = None
    risk_profile: Optional[RiskProfile] = None
    is_default: Optional[bool] = None
    is_auto_rebalance: Optional[bool] = None
    rebalance_frequency: Optional[str] = None
    goal_ids: Optional[List[str]] = None
    target_allocation: Optional[Dict[str, float]] = None
    
    @validator('target_allocation')
    def validate_target_allocation(cls, v):
        if v:
            total = sum(v.values())
            if not (99.0 <= total <= 101.0):  # Allow small rounding errors
                raise ValueError('Target allocation percentages must sum to 100%')
        return v


class HoldingTransaction(BaseModel):
    """Schema for a holding transaction (buy/sell)"""
    portfolio_id: str
    holding_id: Optional[str] = None  # Required for sell, optional for buy
    instrument_name: str  # Required for buy
    instrument_type: Optional[InvestmentType] = None  # Required for buy
    asset_class: Optional[AssetClass] = None  # Required for buy
    transaction_type: str  # buy or sell
    units: float
    price_per_unit: float
    transaction_date: datetime = Field(default_factory=datetime.now)
    notes: Optional[str] = None


class PortfolioPerformanceResponse(BaseModel):
    """Response schema for portfolio performance metrics"""
    current_value: float = 0.0
    invested_value: float = 0.0
    total_gain_loss: float = 0.0
    total_gain_loss_percentage: float = 0.0
    one_day_return: Optional[float] = None
    one_month_return: Optional[float] = None
    three_month_return: Optional[float] = None
    six_month_return: Optional[float] = None
    ytd_return: Optional[float] = None
    one_year_return: Optional[float] = None
    since_inception_return: Optional[float] = None
    volatility: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    last_updated: datetime


class HoldingResponse(HoldingBase):
    """Response schema for investment holding"""
    id: str
    instrument_id: str
    current_value: float
    invested_amount: float
    unrealized_gain_loss: float
    unrealized_gain_loss_percentage: float
    dividend_income: float = 0.0
    last_price_update: datetime
    sector: Optional[str] = None
    industry: Optional[str] = None
    nav: Optional[float] = None
    scheme_code: Optional[str] = None
    folio_number: Optional[str] = None
    exchange: Optional[str] = None
    ticker: Optional[str] = None
    isin: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class AssetAllocationResponse(AssetAllocationBase):
    """Response schema for asset allocation"""
    current_allocation: Dict[str, float] = {}
    target_allocation: Dict[str, float] = {}
    needs_rebalance: bool = False
    last_rebalanced: Optional[datetime] = None


class PortfolioResponse(PortfolioBase):
    """Response schema for portfolio data"""
    id: str
    user_id: str
    holdings: List[HoldingResponse] = []
    performance: PortfolioPerformanceResponse
    asset_allocation: AssetAllocationResponse
    goal_ids: List[str] = []
    is_active: bool = True
    is_default: bool = False
    is_auto_rebalance: bool = False
    rebalance_frequency: Optional[str] = None
    has_recommendations: bool = False
    last_recommendation_date: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "abc12345-1234-5678-abcd-1234567890ab",
                "user_id": "550e8400-e29b-41d4-a716-446655440000",
                "name": "My Retirement Portfolio",
                "description": "Long-term portfolio for retirement planning",
                "portfolio_type": "goal-based",
                "risk_profile": "balanced",
                "performance": {
                    "current_value": 250000.00,
                    "invested_value": 200000.00,
                    "total_gain_loss": 50000.00,
                    "total_gain_loss_percentage": 25.0
                },
                "asset_allocation": {
                    "equity_percentage": 60.0,
                    "debt_percentage": 30.0,
                    "cash_percentage": 10.0
                }
            }
        }


class PortfolioSummaryResponse(BaseModel):
    """Condensed portfolio response for listings"""
    id: str
    name: str
    current_value: float
    invested_value: float
    total_gain_loss_percentage: float
    risk_profile: RiskProfile
    created_at: datetime


class RebalanceRecommendation(BaseModel):
    """Portfolio rebalancing recommendation"""
    portfolio_id: str
    current_allocation: Dict[str, float]
    target_allocation: Dict[str, float]
    recommendations: List[Dict[str, Any]]
    expected_value_change: float