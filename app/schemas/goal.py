from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field, validator
from datetime import datetime, timedelta
from enum import Enum

from app.models.goal import GoalType, GoalStatus, GoalPriority, ContributionFrequency


class MilestoneBase(BaseModel):
    """Base schema for goal milestone"""
    name: str
    target_date: datetime
    target_amount: float
    description: Optional[str] = None
    
    @validator('target_amount')
    def validate_amount(cls, v):
        if not isinstance(v, (int, float)) or v <= 0:
            raise ValueError('Target amount must be a positive number')
        return v
    
    @validator('target_date')
    def validate_date(cls, v):
        if v < datetime.now():
            raise ValueError('Target date must be in the future')
        return v


class MilestoneCreate(MilestoneBase):
    """Schema for creating a new milestone"""
    pass


class MilestoneUpdate(BaseModel):
    """Schema for updating milestone information"""
    name: Optional[str] = None
    target_date: Optional[datetime] = None
    target_amount: Optional[float] = None
    is_achieved: Optional[bool] = None
    achieved_date: Optional[datetime] = None
    description: Optional[str] = None
    
    @validator('target_amount')
    def validate_amount(cls, v):
        if v is not None and (not isinstance(v, (int, float)) or v <= 0):
            raise ValueError('Target amount must be a positive number')
        return v
    
    @validator('target_date')
    def validate_date(cls, v):
        if v is not None and v < datetime.now():
            raise ValueError('Target date must be in the future')
        return v


class GoalBase(BaseModel):
    """Base schema for financial goal"""
    name: str
    description: Optional[str] = None
    goal_type: GoalType
    target_amount: float
    target_date: datetime
    priority: GoalPriority = GoalPriority.MEDIUM
    
    @validator('target_amount')
    def validate_target_amount(cls, v):
        if not isinstance(v, (int, float)) or v <= 0:
            raise ValueError('Target amount must be a positive number')
        return v
    
    @validator('target_date')
    def validate_target_date(cls, v):
        if v < datetime.now():
            raise ValueError('Target date must be in the future')
        return v


class GoalCreate(GoalBase):
    """Schema for creating a new financial goal"""
    user_id: str
    initial_amount: float = 0.0
    icon: Optional[str] = None
    contribution_frequency: ContributionFrequency = ContributionFrequency.MONTHLY
    contribution_amount: float = 0.0
    return_rate: float = 8.0
    risk_profile: str = "moderate"
    portfolio_id: Optional[str] = None
    account_ids: Optional[List[str]] = []
    
    @validator('initial_amount', 'contribution_amount')
    def validate_amount(cls, v):
        if not isinstance(v, (int, float)) or v < 0:
            raise ValueError('Amount must be a non-negative number')
        return v
    
    @validator('return_rate')
    def validate_return_rate(cls, v):
        if not isinstance(v, (int, float)) or v < 0 or v > 30:
            raise ValueError('Return rate must be between 0 and 30 percent')
        return v


class GoalUpdate(BaseModel):
    """Schema for updating goal information"""
    name: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    target_amount: Optional[float] = None
    current_amount: Optional[float] = None
    target_date: Optional[datetime] = None
    status: Optional[GoalStatus] = None
    priority: Optional[GoalPriority] = None
    contribution_frequency: Optional[ContributionFrequency] = None
    contribution_amount: Optional[float] = None
    return_rate: Optional[float] = None
    risk_profile: Optional[str] = None
    portfolio_id: Optional[str] = None
    account_ids: Optional[List[str]] = []
    notes: Optional[str] = None
    
    @validator('target_amount', 'current_amount', 'contribution_amount')
    def validate_amount(cls, v):
        if v is not None and (not isinstance(v, (int, float)) or v < 0):
            raise ValueError('Amount must be a non-negative number')
        return v
    
    @validator('target_date')
    def validate_target_date(cls, v):
        if v is not None and v < datetime.now():
            raise ValueError('Target date must be in the future')
        return v
    
    @validator('return_rate')
    def validate_return_rate(cls, v):
        if v is not None and (not isinstance(v, (int, float)) or v < 0 or v > 30):
            raise ValueError('Return rate must be between 0 and 30 percent')
        return v


class ContributionCreate(BaseModel):
    """Schema for recording a contribution to a goal"""
    goal_id: str
    amount: float
    date: datetime = Field(default_factory=datetime.now)
    source_account_id: Optional[str] = None
    notes: Optional[str] = None
    
    @validator('amount')
    def validate_amount(cls, v):
        if not isinstance(v, (int, float)) or v <= 0:
            raise ValueError('Contribution amount must be a positive number')
        return v


class RecommendedActionResponse(BaseModel):
    """Response schema for AI-recommended actions"""
    id: str
    action_type: str
    description: str
    impact: float
    is_implemented: bool = False
    created_at: datetime


class MilestoneResponse(MilestoneBase):
    """Response schema for milestone data"""
    id: str
    is_achieved: bool = False
    achieved_date: Optional[datetime] = None


class GoalProjection(BaseModel):
    """Projection of goal progress over time"""
    months: List[int]
    projected_amounts: List[float]
    target_line: List[float]
    milestones: List[Dict[str, Any]] = []


class GoalResponse(GoalBase):
    """Response schema for goal data"""
    id: str
    user_id: str
    icon: Optional[str] = None
    current_amount: float = 0.0
    initial_amount: float = 0.0
    start_date: datetime
    status: GoalStatus
    completion_percentage: float = 0.0
    contribution_frequency: ContributionFrequency
    contribution_amount: float = 0.0
    last_contribution_date: Optional[datetime] = None
    next_contribution_date: Optional[datetime] = None
    return_rate: float = 8.0
    risk_profile: str
    milestones: List[MilestoneResponse] = []
    portfolio_id: Optional[str] = None
    account_ids: List[str] = []
    recommended_actions: List[RecommendedActionResponse] = []
    last_ai_review: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    attachments: List[str] = []
    notes: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "def45678-9abc-def0-1234-56789abcdef0",
                "user_id": "550e8400-e29b-41d4-a716-446655440000",
                "name": "Home Down Payment",
                "description": "Save for 20% down payment on a 2BHK apartment",
                "goal_type": "home",
                "target_amount": 2000000.00,
                "current_amount": 500000.00,
                "target_date": "2026-06-01T00:00:00",
                "start_date": "2023-01-15T00:00:00",
                "status": "in_progress",
                "completion_percentage": 25.0,
                "contribution_frequency": "monthly",
                "contribution_amount": 30000.00
            }
        }


class GoalSummaryResponse(BaseModel):
    """Condensed goal response for listings"""
    id: str
    name: str
    goal_type: GoalType
    target_amount: float
    current_amount: float
    target_date: datetime
    completion_percentage: float
    status: GoalStatus
    priority: GoalPriority
    icon: Optional[str] = None