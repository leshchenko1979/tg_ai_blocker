from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class User(BaseModel):
    """Enhanced User model with validation"""

    user_id: int
    username: Optional[str] = None
    credits: int = Field(default=0, ge=0)
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.now)
    last_updated: datetime = Field(default_factory=datetime.now)

    @field_validator("credits")
    @classmethod
    def validate_credits(cls, v):
        if v < 0:
            raise ValueError("Credits cannot be negative")
        return v


class Group(BaseModel):
    """Enhanced Group model with validation"""

    group_id: int
    admin_ids: List[int]
    is_moderation_enabled: bool = True
    member_ids: List[int] = []
    created_at: datetime = Field(default_factory=datetime.now)
    last_updated: datetime = Field(default_factory=datetime.now)


class Message(BaseModel):
    """Model for tracking conversation history"""

    message_id: str
    user_id: int
    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)
