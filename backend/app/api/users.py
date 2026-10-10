"""用户管理路由 /users (admin only)"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from uuid import UUID

from app.core.database import get_db
from app.core.security import hash_password
from app.core.responses import ok, not_found
from app.schemas import schemas
from app.models import *
from app.api.deps import get_current_admin

router = APIRouter(prefix="/users", tags=["用户管理"])


@router.get("")
def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    role: str | None = Query(None),
    keyword: str | None = Query(None),
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
):
    q = db.query(User)
    if role:
        q = q.filter(User.role == role)
    if keyword:
        q = q.filter(
            (User.username.ilike(f"%{keyword}%")) |
            (User.email.ilike(f"%{keyword}%"))
        )
    total = q.count()
    items = q.order_by(User.created_at.desc()) \
        .offset((page - 1) * page_size).limit(page_size).all()
    return ok({
        "items": [schemas.UserOut.model_validate(u) for u in items],
        "total": total, "page": page, "page_size": page_size,
    })


@router.post("")
def create_user(req: schemas.UserCreateReq,
                db: Session = Depends(get_db),
                _admin: User = Depends(get_current_admin)):
    if db.query(User).filter_by(username=req.username).first():
        from app.core.responses import param_error
        raise param_error("用户名已存在")
    user = User(
        username=req.username, email=req.email,
        password_hash=hash_password(req.password),
        role=req.role, display_name=req.display_name or req.username,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return ok(schemas.UserOut.model_validate(user))


@router.get("/{user_id}")
def get_user(user_id: UUID, db: Session = Depends(get_db),
             _admin: User = Depends(get_current_admin)):
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise not_found("用户不存在")
    return ok(schemas.UserOut.model_validate(user))


@router.put("/{user_id}")
def update_user(user_id: UUID, req: schemas.UserUpdateReq,
                db: Session = Depends(get_db),
                _admin: User = Depends(get_current_admin)):
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise not_found("用户不存在")
    data = req.model_dump(exclude_unset=True)
    if "password" in data and data["password"]:
        user.password_hash = hash_password(data.pop("password"))
    for k, v in data.items():
        if v is not None:
            setattr(user, k, v)
    db.commit()
    db.refresh(user)
    return ok(schemas.UserOut.model_validate(user))


@router.delete("/{user_id}")
def disable_user(user_id: UUID, db: Session = Depends(get_db),
                 _admin: User = Depends(get_current_admin)):
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise not_found("用户不存在")
    if user.role == "admin" and user.username == "admin":
        from app.core.responses import param_error
        raise param_error("不能停用超级管理员")
    user.is_active = False
    db.commit()
    return ok({})
