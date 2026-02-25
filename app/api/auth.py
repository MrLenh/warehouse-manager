from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["Auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: str
    username: str
    display_name: str
    role: str
    active: bool = True
    created_at: str = ""

    model_config = {"from_attributes": True}


class CreateUserRequest(BaseModel):
    username: str
    password: str
    display_name: str = ""
    role: str = "staff"


class ActivityLogOut(BaseModel):
    id: str
    user_id: str
    username: str
    action: str
    detail: str
    ip_address: str
    created_at: str

    model_config = {"from_attributes": True}


def get_current_user(
    request: Request,
    token: str | None = Cookie(default=None, alias="token"),
    db: Session = Depends(get_db),
) -> User:
    """Dependency: extract user from JWT cookie."""
    if not token:
        raise HTTPException(401, "Not authenticated")
    payload = auth_service.decode_token(token)
    if not payload:
        raise HTTPException(401, "Invalid or expired token")
    user = auth_service.get_user_by_id(db, payload["sub"])
    if not user or not user.active:
        raise HTTPException(401, "User not found or disabled")
    return user


@router.post("/login")
def login(data: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    user = auth_service.authenticate(db, data.username, data.password)
    if not user:
        raise HTTPException(401, "Invalid username or password")
    token = auth_service.create_access_token(user.id, user.username)
    response.set_cookie("token", token, httponly=True, samesite="lax", max_age=3600 * 72)
    auth_service.log_activity(db, user.id, user.username, "login", ip=request.client.host if request.client else "")
    return {"token": token, "user": UserOut.model_validate(user)}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("token")
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return UserOut(
        id=user.id, username=user.username, display_name=user.display_name,
        role=user.role, active=user.active,
        created_at=user.created_at.isoformat() if user.created_at else "",
    )


@router.get("/users")
def list_users(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "admin":
        raise HTTPException(403, "Admin only")
    users = auth_service.list_users(db)
    return [
        UserOut(
            id=u.id, username=u.username, display_name=u.display_name,
            role=u.role, active=u.active,
            created_at=u.created_at.isoformat() if u.created_at else "",
        ) for u in users
    ]


@router.post("/users", status_code=201)
def create_user(data: CreateUserRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "admin":
        raise HTTPException(403, "Admin only")
    try:
        u = auth_service.create_user(db, data.username, data.password, data.display_name, data.role)
    except ValueError as e:
        raise HTTPException(400, str(e))
    auth_service.log_activity(db, user.id, user.username, "create_user", detail=f"Created user: {data.username}")
    return UserOut(
        id=u.id, username=u.username, display_name=u.display_name,
        role=u.role, active=u.active,
        created_at=u.created_at.isoformat() if u.created_at else "",
    )


class UpdateUserRequest(BaseModel):
    display_name: str | None = None
    role: str | None = None


class ChangePasswordRequest(BaseModel):
    password: str


@router.patch("/users/{user_id}")
def update_user(user_id: str, data: UpdateUserRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "admin":
        raise HTTPException(403, "Admin only")
    target = auth_service.get_user_by_id(db, user_id)
    if not target:
        raise HTTPException(404, "User not found")
    if data.display_name is not None:
        target.display_name = data.display_name
    if data.role is not None:
        target.role = data.role
    db.commit()
    db.refresh(target)
    auth_service.log_activity(db, user.id, user.username, "update_user", detail=f"Updated {target.username}: role={target.role}")
    return UserOut(
        id=target.id, username=target.username, display_name=target.display_name,
        role=target.role, active=target.active,
        created_at=target.created_at.isoformat() if target.created_at else "",
    )


@router.patch("/users/{user_id}/active")
def toggle_user_active(user_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "admin":
        raise HTTPException(403, "Admin only")
    target = auth_service.get_user_by_id(db, user_id)
    if not target:
        raise HTTPException(404, "User not found")
    if target.id == user.id:
        raise HTTPException(400, "Cannot disable yourself")
    target.active = not target.active
    db.commit()
    db.refresh(target)
    status = "enabled" if target.active else "disabled"
    auth_service.log_activity(db, user.id, user.username, "toggle_user", detail=f"{target.username} → {status}")
    return {"id": target.id, "active": target.active}


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: str, data: ChangePasswordRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "admin":
        raise HTTPException(403, "Admin only")
    target = auth_service.get_user_by_id(db, user_id)
    if not target:
        raise HTTPException(404, "User not found")
    target.password_hash = auth_service.hash_password(data.password)
    db.commit()
    auth_service.log_activity(db, user.id, user.username, "reset_password", detail=f"Reset password for {target.username}")
    return {"ok": True}


@router.post("/change-password")
def change_own_password(data: ChangePasswordRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user.password_hash = auth_service.hash_password(data.password)
    db.commit()
    auth_service.log_activity(db, user.id, user.username, "change_password")
    return {"ok": True}


@router.get("/activity", response_model=list[ActivityLogOut])
def activity_logs(
    limit: int = 100,
    user_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    logs = auth_service.get_activity_logs(db, limit=limit, user_id=user_id)
    return [
        ActivityLogOut(
            id=l.id,
            user_id=l.user_id,
            username=l.username,
            action=l.action,
            detail=l.detail,
            ip_address=l.ip_address,
            created_at=l.created_at.isoformat() if l.created_at else "",
        )
        for l in logs
    ]
