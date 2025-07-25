from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime
import uuid
from enum import Enum

from app.utils.helpers import get_current_time_ist

class MessageRole(str, Enum):
    """Roles in a chat conversation"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"

class MessageType(str, Enum):
    """Types of messages in a chat"""
    TEXT = "text"
    RICH_TEXT = "rich_text"
    IMAGE = "image"
    FILE = "file"
    CHART = "chart"
    RECOMMENDATION = "recommendation"
    ACTION = "action"

class EntityType(str, Enum):
    """Types of entities referenced in messages"""
    ACCOUNT = "account"
    TRANSACTION = "transaction"
    PORTFOLIO = "portfolio"
    INVESTMENT = "investment"
    GOAL = "goal"
    BUDGET = "budget"
    FINANCIAL_TERM = "financial_term"
    INVESTMENT_PRODUCT = "investment_product"

class Entity(BaseModel):
    """Entity referenced in a message"""
    id: str
    type: EntityType
    name: str
    value: Optional[Any] = None
    start_index: Optional[int] = None
    end_index: Optional[int] = None

class Message(BaseModel):
    """Individual message in a chat session"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    role: MessageRole
    content: str
    message_type: MessageType = MessageType.TEXT
    
    # Rich content
    rich_content: Optional[Dict[str, Any]] = None
    
    # Entity extraction
    entities: List[Entity] = []
    
    # Financial data references
    references: List[Dict[str, Any]] = []
    
    # Message metadata
    created_at: datetime = Field(default_factory=get_current_time_ist)
    read_at: Optional[datetime] = None
    
    # Context tracking
    context_id: Optional[str] = None
    parent_message_id: Optional[str] = None
    
    # AI metadata
    ai_model: Optional[str] = None
    tokens_used: Optional[int] = None
    processing_time: Optional[float] = None

class ChatSession(BaseModel):
    """
    Chat session model representing a conversation between user and AI
    
    This includes the conversation history and context for the AI assistant
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    
    # Session details
    title: str
    description: Optional[str] = None
    session_type: str = "general"  # general, goal_planning, investment_advice, etc.
    
    # Status
    is_active: bool = True
    last_message_at: Optional[datetime] = None
    
    # Context and state
    context: Dict[str, Any] = {}
    
    # Session history compaction
    summary: Optional[str] = None
    
    # Financial context
    related_goal_ids: List[str] = []
    related_portfolio_ids: List[str] = []
    related_account_ids: List[str] = []
    
    # Metadata
    created_at: datetime = Field(default_factory=get_current_time_ist)
    updated_at: datetime = Field(default_factory=get_current_time_ist)
    
    # Analytics
    interaction_count: int = 0
    sentiment_score: Optional[float] = None
    satisfaction_rating: Optional[int] = None
    
    # Message IDs (for reference)
    message_ids: List[str] = []
    
    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "550e8400-e29b-41d4-a716-446655440000",
                "title": "Retirement Planning",
                "description": "Conversation about retirement planning options",
                "session_type": "goal_planning",
                "context": {
                    "current_topic": "retirement",
                    "user_age": 35,
                    "risk_profile": "moderate"
                }
            }
        }