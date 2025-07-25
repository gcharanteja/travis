from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, validator
from datetime import datetime
from enum import Enum

from app.models.chat import MessageRole, MessageType, EntityType


class EntityBase(BaseModel):
    """Base schema for entity referenced in a message"""
    type: EntityType
    name: str
    value: Optional[Any] = None
    start_index: Optional[int] = None
    end_index: Optional[int] = None


class MessageBase(BaseModel):
    """Base schema for chat message"""
    content: str
    message_type: MessageType = MessageType.TEXT
    rich_content: Optional[Dict[str, Any]] = None


class MessageCreate(MessageBase):
    """Schema for creating a new message"""
    session_id: str
    role: MessageRole = MessageRole.USER
    context_id: Optional[str] = None
    parent_message_id: Optional[str] = None


class ChatSessionBase(BaseModel):
    """Base schema for chat session"""
    title: str
    description: Optional[str] = None
    session_type: str = "general"


class ChatSessionCreate(ChatSessionBase):
    """Schema for creating a new chat session"""
    user_id: str
    context: Optional[Dict[str, Any]] = None
    related_goal_ids: Optional[List[str]] = None
    related_portfolio_ids: Optional[List[str]] = None
    related_account_ids: Optional[List[str]] = None


class ChatSessionUpdate(BaseModel):
    """Schema for updating chat session"""
    title: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    satisfaction_rating: Optional[int] = None
    context: Optional[Dict[str, Any]] = None
    
    @validator('satisfaction_rating')
    def validate_rating(cls, v):
        if v is not None and (not isinstance(v, int) or v < 1 or v > 5):
            raise ValueError('Rating must be an integer between 1 and 5')
        return v


class EntityResponse(EntityBase):
    """Response schema for entity data"""
    id: str


class MessageResponse(MessageBase):
    """Response schema for message data"""
    id: str
    session_id: str
    role: MessageRole
    entities: List[EntityResponse] = []
    references: List[Dict[str, Any]] = []
    created_at: datetime
    read_at: Optional[datetime] = None
    context_id: Optional[str] = None
    parent_message_id: Optional[str] = None
    ai_model: Optional[str] = None
    tokens_used: Optional[int] = None
    processing_time: Optional[float] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "ghi78901-2345-6789-abcd-ef0123456789",
                "session_id": "jkl90123-4567-890a-bcde-f01234567890",
                "role": "user",
                "content": "How much have I spent on dining out this month?",
                "message_type": "text",
                "created_at": "2023-06-01T14:30:00"
            }
        }


class ChatSessionResponse(ChatSessionBase):
    """Response schema for chat session data"""
    id: str
    user_id: str
    is_active: bool = True
    last_message_at: Optional[datetime] = None
    context: Dict[str, Any] = {}
    summary: Optional[str] = None
    related_goal_ids: List[str] = []
    related_portfolio_ids: List[str] = []
    related_account_ids: List[str] = []
    created_at: datetime
    updated_at: datetime
    interaction_count: int = 0
    sentiment_score: Optional[float] = None
    satisfaction_rating: Optional[int] = None
    recent_messages: List[MessageResponse] = []
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "jkl90123-4567-890a-bcde-f01234567890",
                "user_id": "550e8400-e29b-41d4-a716-446655440000",
                "title": "Investment Strategy Discussion",
                "description": "Chat about optimizing my investment portfolio",
                "session_type": "investment_advice",
                "is_active": True,
                "created_at": "2023-06-01T10:00:00",
                "interaction_count": 12
            }
        }


class ChatSessionSummaryResponse(BaseModel):
    """Condensed chat session response for listings"""
    id: str
    title: str
    session_type: str
    last_message_at: Optional[datetime] = None
    created_at: datetime
    interaction_count: int
    last_message_preview: Optional[str] = None


class AICoachQuestion(BaseModel):
    """Schema for asking a question to the AI coach"""
    user_id: str
    question: str
    session_id: Optional[str] = None
    context: Optional[Dict[str, Any]] = None