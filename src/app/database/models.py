from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class Administrator(BaseModel):
    """Enhanced administrator model with validation"""

    admin_id: int
    username: Optional[str] = None
    credits: int = Field(default=0, ge=0)
    is_active: bool = True
    delete_spam: bool = True  # Default to True for spam message deletion
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
    moderation_enabled: bool = True
    member_ids: List[int] = []
    created_at: datetime = Field(default_factory=datetime.now)
    last_updated: datetime = Field(default_factory=datetime.now)
