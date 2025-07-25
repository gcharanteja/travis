from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime
import uuid
from enum import Enum

from app.utils.helpers import get_current_time_ist

class AssetClass(str, Enum):
    """Asset classes for investments"""
    EQUITY = "equity"
    DEBT = "debt"
    CASH = "cash"
    REAL_ESTATE = "real_estate"
    GOLD = "gold"
    ALTERNATIVE = "alternative"
    CRYPTO = "crypto"

class InvestmentType(str, Enum):
    """Types of investment instruments"""
    STOCK = "stock"
    MUTUAL_FUND = "mutual_fund"
    ETF = "etf"
    BOND = "bond"
    FD = "fixed_deposit"
    PPF = "ppf"
    EPF = "epf"
    NPS = "nps"
    REAL_ESTATE = "real_estate"
    GOLD = "gold"
    CRYPTO = "cryptocurrency"
    OTHER = "other"

class RiskProfile(str, Enum):
    """Risk profiles for portfolios and investments"""
    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    BALANCED = "balanced"
    GROWTH = "growth"
    AGGRESSIVE = "aggressive"

class InvestmentHolding(BaseModel):
    """Individual investment holding within a portfolio"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    instrument_id: str  # ID of the investment instrument
    instrument_name: str
    instrument_type: InvestmentType
    
    # Quantity and valuation
    units: float
    average_buy_price: float
    current_price: float
    current_value: float
    invested_amount: float
    
    # Classification
    asset_class: AssetClass
    sector: Optional[str] = None
    industry: Optional[str] = None
    
    # Performance
    unrealized_gain_loss: float = 0.0
    unrealized_gain_loss_percentage: float = 0.0
    dividend_income: float = 0.0
    last_price_update: datetime = Field(default_factory=get_current_time_ist)
    
    # For mutual funds
    nav: Optional[float] = None
    scheme_code: Optional[str] = None
    folio_number: Optional[str] = None
    
    # For stocks
    exchange: Optional[str] = None  # NSE, BSE, etc.
    ticker: Optional[str] = None
    isin: Optional[str] = None
    
    # Transaction history IDs
    transaction_ids: List[str] = []
    
    # Metadata
    created_at: datetime = Field(default_factory=get_current_time_ist)
    updated_at: datetime = Field(default_factory=get_current_time_ist)

class PortfolioPerformance(BaseModel):
    """Performance metrics for a portfolio"""
    current_value: float = 0.0
    invested_value: float = 0.0
    total_gain_loss: float = 0.0
    total_gain_loss_percentage: float = 0.0
    
    # Time-based returns
    one_day_return: Optional[float] = None
    one_week_return: Optional[float] = None
    one_month_return: Optional[float] = None
    three_month_return: Optional[float] = None
    six_month_return: Optional[float] = None
    ytd_return: Optional[float] = None
    one_year_return: Optional[float] = None
    three_year_return: Optional[float] = None
    five_year_return: Optional[float] = None
    since_inception_return: Optional[float] = None
    
    # Risk metrics
    volatility: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    alpha: Optional[float] = None
    beta: Optional[float] = None
    
    # Dividend metrics
    total_dividend_income: float = 0.0
    dividend_yield: Optional[float] = None
    
    # Last updated
    last_updated: datetime = Field(default_factory=get_current_time_ist)

class AssetAllocation(BaseModel):
    """Asset allocation for a portfolio"""
    equity_percentage: float = 0.0
    debt_percentage: float = 0.0
    cash_percentage: float = 0.0
    real_estate_percentage: float = 0.0
    gold_percentage: float = 0.0
    alternative_percentage: float = 0.0
    crypto_percentage: float = 0.0
    
    # Current allocation
    current_allocation: Dict[str, float] = {}
    
    # Target allocation
    target_allocation: Dict[str, float] = {}
    
    # Rebalance status
    needs_rebalance: bool = False
    last_rebalanced: Optional[datetime] = None

class Portfolio(BaseModel):
    """
    Portfolio model representing a collection of investments
    
    This includes stocks, mutual funds, and other investment instruments
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    
    # Portfolio details
    name: str
    description: Optional[str] = None
    portfolio_type: str = "custom"  # custom, recommended, goal-based, etc.
    risk_profile: RiskProfile = RiskProfile.MODERATE
    
    # Holdings
    holdings: List[InvestmentHolding] = []
    
    # Performance metrics
    performance: PortfolioPerformance = PortfolioPerformance()
    
    # Asset allocation
    asset_allocation: AssetAllocation = AssetAllocation()
    
    # Related goals
    goal_ids: List[str] = []
    
    # Portfolio settings
    is_active: bool = True
    is_default: bool = False
    is_auto_rebalance: bool = False
    rebalance_frequency: Optional[str] = None  # monthly, quarterly, etc.
    
    # AI recommendations
    has_recommendations: bool = False
    last_recommendation_date: Optional[datetime] = None
    
    # Metadata
    created_at: datetime = Field(default_factory=get_current_time_ist)
    updated_at: datetime = Field(default_factory=get_current_time_ist)
    
    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "550e8400-e29b-41d4-a716-446655440000",
                "name": "My Long Term Portfolio",
                "description": "Portfolio for retirement planning",
                "portfolio_type": "goal-based",
                "risk_profile": "balanced",
                "holdings": [
                    {
                        "instrument_name": "Axis Bluechip Fund Direct Growth",
                        "instrument_type": "mutual_fund",
                        "units": 500.235,
                        "average_buy_price": 45.75,
                        "current_price": 50.25,
                        "current_value": 25136.81,
                        "invested_amount": 22898.25,
                        "asset_class": "equity",
                        "scheme_code": "122546",
                        "folio_number": "12345678"
                    }
                ]
            }
        }