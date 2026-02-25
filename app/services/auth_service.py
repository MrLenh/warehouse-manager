from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.models.user import ActivityLog, User


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_access_token(user_id: str, username: str) -> str:
    payload = {
        "sub": user_id,
        "username": username,
        "exp": datetime.now(timezone.utc) + timedelta(hours=settings.ACCESS_TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


def authenticate(db: Session, username: str, password: str) -> User | None:
    user = db.query(User).filter(User.username == username, User.active == True).first()
    if not user or not verify_password(password, user.password_hash):
        return None
    return user


def get_user_by_id(db: Session, user_id: str) -> User | None:
    return db.query(User).filter(User.id == user_id).first()


def create_user(db: Session, username: str, password: str, display_name: str = "", role: str = "staff") -> User:
    existing = db.query(User).filter(User.username == username).first()
    if existing:
        raise ValueError(f"Username '{username}' already exists")
    user = User(
        username=username,
        display_name=display_name or username,
        password_hash=hash_password(password),
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def list_users(db: Session) -> list[User]:
    return db.query(User).order_by(User.created_at.desc()).all()


def ensure_default_admin(db: Session) -> None:
    """Create default admin user if no users exist."""
    count = db.query(User).count()
    if count == 0:
        create_user(db, username="admin", password="admin", display_name="Admin", role="admin")


# Activity logging

def log_activity(db: Session, user_id: str, username: str, action: str, detail: str = "", ip: str = "") -> None:
    entry = ActivityLog(
        user_id=user_id,
        username=username,
        action=action,
        detail=detail,
        ip_address=ip,
    )
    db.add(entry)
    db.commit()


def get_activity_logs(db: Session, limit: int = 100, user_id: str | None = None) -> list[ActivityLog]:
    q = db.query(ActivityLog)
    if user_id:
        q = q.filter(ActivityLog.user_id == user_id)
    return q.order_by(ActivityLog.created_at.desc()).limit(limit).all()
