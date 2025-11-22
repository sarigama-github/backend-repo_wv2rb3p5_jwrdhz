import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Literal, Dict, Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, EmailStr
from bson import ObjectId

from database import db
from schemas import Team, TeamSettings, User, UserDevice, Record, LogEntry, JournalEntry, Reminder, StickyNote

# ---------- Helpers ----------

class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if isinstance(v, ObjectId):
            return v
        try:
            return ObjectId(str(v))
        except Exception:
            raise ValueError("Invalid ObjectId")

def oid(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")

# ---------- App ----------

app = FastAPI(title="Team Logger API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Root & Health ----------

@app.get("/")
def read_root():
    return {"message": "Team Logger API Running"}

@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": "❌ Not Set",
        "database_name": "❌ Not Set",
        "connection_status": "Not Connected",
        "collections": [],
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name
            response["connection_status"] = "Connected"
            try:
                response["collections"] = db.list_collection_names()
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but error: {str(e)[:80]}"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response

# ---------- Users ----------

class CreateUserRequest(BaseModel):
    email: EmailStr
    name: str
    password: str = Field(..., min_length=6)
    age: Optional[int] = Field(None, ge=0, le=120)
    theme_preference: Literal["family", "neutral"] = "family"

@app.post("/api/users")
def create_user(payload: CreateUserRequest):
    if db["user"].find_one({"email": payload.email}):
        raise HTTPException(status_code=409, detail="Email already registered")
    user = User(
        email=payload.email,
        name=payload.name,
        password_hash=f"hash:{payload.password}",  # Placeholder for MVP
        age=payload.age,
        theme_preference=payload.theme_preference,
    ).model_dump()
    res = db["user"].insert_one({**user, "created_at": datetime.now(timezone.utc)})
    return {"_id": str(res.inserted_id)}

class RegisterDeviceRequest(BaseModel):
    user_id: str
    platform: Optional[str] = None
    push_token: Optional[str] = None

@app.post("/api/devices/register")
def register_device(payload: RegisterDeviceRequest):
    u = db["user"].find_one({"_id": oid(payload.user_id)})
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    device = UserDevice(platform=payload.platform, push_token=payload.push_token, last_active_at=datetime.now(timezone.utc)).model_dump()
    db["user"].update_one({"_id": oid(payload.user_id)}, {"$push": {"devices": device}})
    return {"status": "ok"}

# ---------- Teams ----------

class CreateTeamRequest(BaseModel):
    name: str
    leader_user_id: str

@app.post("/api/teams")
def create_team(payload: CreateTeamRequest):
    if not db["user"].find_one({"_id": oid(payload.leader_user_id)}):
        raise HTTPException(status_code=404, detail="Leader user not found")
    team = Team(name=payload.name, leader_id=payload.leader_user_id)
    team_dict = team.model_dump()
    res = db["team"].insert_one({**team_dict, "created_at": datetime.now(timezone.utc)})
    # Add role to leader
    db["user"].update_one({"_id": oid(payload.leader_user_id)}, {"$set": {f"roles.{str(res.inserted_id)}": "leader"}})
    return {"_id": str(res.inserted_id)}

class InviteRequest(BaseModel):
    email: EmailStr

@app.post("/api/teams/{team_id}/invite")
def invite(team_id: str, payload: InviteRequest):
    if not db["team"].find_one({"_id": oid(team_id)}):
        raise HTTPException(status_code=404, detail="Team not found")
    db["team"].update_one({"_id": oid(team_id)}, {"$addToSet": {"invites": payload.email}})
    return {"status": "ok"}

class JoinTeamRequest(BaseModel):
    user_id: str

@app.post("/api/teams/{team_id}/join")
def join_team(team_id: str, payload: JoinTeamRequest):
    t = db["team"].find_one({"_id": oid(team_id)})
    if not t:
        raise HTTPException(status_code=404, detail="Team not found")
    if not db["user"].find_one({"_id": oid(payload.user_id)}):
        raise HTTPException(status_code=404, detail="User not found")
    db["team"].update_one({"_id": oid(team_id)}, {"$addToSet": {"member_ids": payload.user_id}})
    db["user"].update_one({"_id": oid(payload.user_id)}, {"$set": {f"roles.{team_id}": "adult"}})
    return {"status": "ok"}

@app.get("/api/teams/{team_id}")
def get_team(team_id: str):
    t = db["team"].find_one({"_id": oid(team_id)})
    if not t:
        raise HTTPException(status_code=404, detail="Team not found")
    t["_id"] = str(t["_id"]) 
    return t

# ---------- Records: Logs & Journals ----------

class CreateRecordRequest(BaseModel):
    team_id: str
    author_id: str
    type: Literal["log", "journal"]
    content: str
    is_private: bool = False
    tags: List[str] = []
    occurred_at: Optional[datetime] = None
    title: Optional[str] = None

@app.post("/api/records")
def create_record(payload: CreateRecordRequest):
    if payload.type == "log":
        rec = LogEntry(team_id=payload.team_id, author_id=payload.author_id, content=payload.content, tags=payload.tags, is_private=payload.is_private, occurred_at=payload.occurred_at)
    else:
        rec = JournalEntry(team_id=payload.team_id, author_id=payload.author_id, content=payload.content, tags=payload.tags, is_private=payload.is_private, title=payload.title)
    doc = rec.model_dump()
    now = datetime.now(timezone.utc)
    doc.update({"created_at": now, "updated_at": now})
    res = db["record"].insert_one(doc)
    return {"_id": str(res.inserted_id)}

@app.get("/api/records")
def list_records(
    team_id: str = Query(...),
    requester_id: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    include_deleted: bool = False,
):
    q: Dict[str, Any] = {"team_id": team_id}
    if type:
        q["type"] = type
    if not include_deleted:
        q["deleted_at"] = {"$exists": False}
    items = list(db["record"].find(q).sort("created_at", -1))
    # Privacy filter: hide private records from non-authors by default
    filtered = []
    for it in items:
        if it.get("is_private") and requester_id and requester_id != it.get("author_id"):
            continue
        it["_id"] = str(it["_id"]) 
        filtered.append(it)
    return filtered

class UpdateRecordRequest(BaseModel):
    content: Optional[str] = None
    is_private: Optional[bool] = None
    tags: Optional[List[str]] = None
    occurred_at: Optional[datetime] = None
    title: Optional[str] = None

@app.put("/api/records/{record_id}")
def update_record(record_id: str, payload: UpdateRecordRequest):
    updates = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    updates["updated_at"] = datetime.now(timezone.utc)
    res = db["record"].update_one({"_id": oid(record_id)}, {"$set": updates})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Record not found")
    return {"status": "ok"}

@app.delete("/api/records/{record_id}")
def soft_delete_record(record_id: str):
    now = datetime.now(timezone.utc)
    purge = now + timedelta(days=30)
    res = db["record"].update_one({"_id": oid(record_id)}, {"$set": {"deleted_at": now, "purge_at": purge}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Record not found")
    return {"status": "moved_to_trash", "purge_at": purge.isoformat()}

# ---------- Trash ----------

@app.get("/api/trash")
def list_trash(team_id: str):
    items = list(db["record"].find({"team_id": team_id, "deleted_at": {"$exists": True}}).sort("deleted_at", -1))
    for it in items:
        it["_id"] = str(it["_id"]) 
    return items

@app.post("/api/trash/{record_id}/restore")
def restore_record(record_id: str):
    res = db["record"].update_one({"_id": oid(record_id)}, {"$unset": {"deleted_at": "", "purge_at": ""}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Record not found")
    return {"status": "restored"}

@app.delete("/api/trash/purge")
def purge_expired(team_id: Optional[str] = None, record_id: Optional[str] = None):
    if record_id:
        res = db["record"].delete_one({"_id": oid(record_id)})
        return {"deleted": res.deleted_count}
    q: Dict[str, Any] = {"purge_at": {"$lte": datetime.now(timezone.utc)}}
    if team_id:
        q["team_id"] = team_id
    res = db["record"].delete_many(q)
    return {"deleted": res.deleted_count}

# ---------- Reminders (MVP: store + list; scheduling worker out of scope) ----------

class CreateReminderRequest(BaseModel):
    team_id: str
    creator_id: str
    title: str
    notes: Optional[str] = None
    schedule_iso: str
    recipient_ids: List[str] = Field(default_factory=list)
    send_push: bool = True

@app.post("/api/reminders")
def create_reminder(payload: CreateReminderRequest):
    rem = Reminder(**payload.model_dump()).model_dump()
    now = datetime.now(timezone.utc)
    res = db["reminder"].insert_one({**rem, "created_at": now})
    return {"_id": str(res.inserted_id)}

@app.get("/api/reminders")
def list_reminders(team_id: str):
    items = list(db["reminder"].find({"team_id": team_id}).sort("created_at", -1))
    for it in items:
        it["_id"] = str(it["_id"]) 
    return items

# Note: Push delivery and real scheduling will be added in a later step.

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
