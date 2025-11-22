"""
Team Logger Schemas

Each Pydantic model represents a collection in MongoDB.
Collection name is the lowercase class name, e.g. User -> "user".

Age and privacy policy
- Base private journal threshold is 15+
- Children 12–14 may request private journal access from Team Leader
These are defaults and can be overridden per-team via settings.
"""
from __future__ import annotations
from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, Field, EmailStr
from datetime import datetime

# ---------- Core ----------

class TeamSettings(BaseModel):
    private_journal_age: int = Field(15, ge=0, le=120)
    request_private_from_age: int = Field(12, ge=0, le=120)
    locale: str = Field("en", description="Default locale for the team")
    theme_default: Literal["family", "neutral"] = Field("family")

class Team(BaseModel):
    name: str
    leader_id: str = Field(..., description="User _id of the team leader")
    member_ids: List[str] = Field(default_factory=list)
    invites: List[str] = Field(default_factory=list, description="Pending invite emails")
    settings: TeamSettings = Field(default_factory=TeamSettings)
    subscription_tier: Literal["starter", "pro", "business"] = Field("starter")

class UserDevice(BaseModel):
    platform: Optional[str] = None
    push_token: Optional[str] = None
    last_active_at: Optional[datetime] = None

class User(BaseModel):
    email: EmailStr
    name: str
    password_hash: str
    age: Optional[int] = Field(None, ge=0, le=120)
    roles: Dict[str, Literal["leader", "adult", "young_adult", "teen", "kid"]] = Field(
        default_factory=dict, description="team_id -> role"
    )
    devices: List[UserDevice] = Field(default_factory=list)
    theme_preference: Literal["family", "neutral"] = Field("family")

# ---------- Records ----------

class Record(BaseModel):
    team_id: str
    author_id: str
    type: Literal["log", "journal"]
    content: str
    tags: List[str] = Field(default_factory=list)
    is_private: bool = False
    edited_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    purge_at: Optional[datetime] = None

class LogEntry(Record):
    type: Literal["log"] = "log"
    occurred_at: Optional[datetime] = None

class JournalEntry(Record):
    type: Literal["journal"] = "journal"
    title: Optional[str] = None

# ---------- Reminders ----------

class Reminder(BaseModel):
    team_id: str
    creator_id: str
    title: str
    notes: Optional[str] = None
    schedule_iso: str = Field(..., description="RFC3339/ISO8601 date or RRULE string")
    recipient_ids: List[str] = Field(default_factory=list)
    send_push: bool = True

# ---------- Sticky Notes (later phase; schema stub for future) ----------

class StickyNote(BaseModel):
    team_id: str
    creator_id: str
    text: str = Field(..., max_length=240)
    recipient_ids: List[str] = Field(default_factory=list)
    pop_on_open: bool = True
    send_push: bool = False

