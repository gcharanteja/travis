from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field
from datetime import datetime
import uuid
from enum import Enum

from app.utils.helpers import get_current_time_ist

class GoalType(str, Enum):
    """Types of financial goals"""
    RETIREMENT = "retirement"
    EDUCATION = "education"
    HOME = "home"
    VEHICLE = "vehicle"
    TRAVEL = "travel"
    WEDDING = "wedding"
    EMERGENCY_FUND = "emergency_fund"
    DEBT_PAYOFF = "debt_payoff"
    MAJOR_PURCHASE = "major_purchase"
    OTHER = "other"

class GoalStatus(str, Enum):
    """Status of financial goals"""
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    ON_TRACK = "on_track"
    BEHIND_SCHEDULE = "behind_schedule"
    AHEAD_OF_SCHEDULE = "ahead_of_schedule"
    ACHIEVED = "achieved"
    CANCELLED = "cancelled"

class GoalPriority(str, Enum):
    """Priority levels for goals"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class ContributionFrequency(str, Enum):
    """Frequency of contributions to goals"""
    ONE_TIME = "one_time"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    HALF_YEARLY = "half_yearly"
    YEARLY = "yearly"

class GoalMilestone(BaseModel):
    """Milestone within a financial goal"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    target_date: datetime
    target_amount: float
    is_achieved: bool = False
    achieved_date: Optional[datetime] = None
    description: Optional[str] = None
    
class RecommendedAction(BaseModel):
    """AI-recommended actions for achieving goals"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    action_type: str  # increase_contribution, adjust_allocation, etc.
    description: str
    impact: float  # Estimated impact on goal
    is_implemented: bool = False
    created_at: datetime = Field(default_factory=get_current_time_ist)

class Goal(BaseModel):
    """
    Goal model representing a financial goal for a user
    
    This includes savings targets, investment goals, and other financial objectives
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    
    # Goal details
    name: str
    description: Optional[str] = None
    goal_type: GoalType
    icon: Optional[str] = None  # Icon identifier or URL
    
    # Financial details
    target_amount: float
    current_amount: float = 0.0
    initial_amount: float = 0.0
    
    # Time frame
    target_date: datetime
    start_date: datetime = Field(default_factory=get_current_time_ist)
    
    # Status and progress
    status: GoalStatus = GoalStatus.NOT_STARTED
    completion_percentage: float = 0.0
    priority: GoalPriority = GoalPriority.MEDIUM
    
    # Contribution plan
    contribution_frequency: ContributionFrequency = ContributionFrequency.MONTHLY
    contribution_amount: float = 0.0
    last_contribution_date: Optional[datetime] = None
    next_contribution_date: Optional[datetime] = None
    
    # Investment strategy
    return_rate: float = 8.0  # Expected annual return rate (%)
    risk_profile: str = "moderate"  # From portfolio risk profile enum
    
    # Progress tracking
    contributions: List[Dict[str, Union[datetime, float, str]]] = []
    milestones: List[GoalMilestone] = []
    
    # Connected assets
    portfolio_id: Optional[str] = None
    account_ids: List[str] = []
    
    # AI recommendations
    recommended_actions: List[RecommendedAction] = []
    last_ai_review: Optional[datetime] = None
    
    # Metadata
    created_at: datetime = Field(default_factory=get_current_time_ist)
    updated_at: datetime = Field(default_factory=get_current_time_ist)
    
    # Additional info
    attachments: List[str] = []  # URLs to related documents
    notes: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "550e8400-e29b-41d4-a716-446655440000",
                "name": "Down Payment for Home",
                "description": "Save for 20% down payment on a house in Bangalore",
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