"""认证路由 /auth"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from uuid import UUID

from app.core.database import get_db
from app.core.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
)
from app.core.responses import ok, not_found, param_error
from app.schemas import schemas
from app.models import *
from app.api.deps import get_current_user

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/login")
def login(req: schemas.LoginReq, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(username=req.username).first()
    if not user or not verify_password(req.password, user.password_hash):
        raise param_error("用户名或密码错误")
    if not user.is_active:
        raise param_error("用户已被停用")
    return ok({
        "access_token": create_access_token(str(user.id)),
        "refresh_token": create_refresh_token(str(user.id)),
        "token_type": "bearer",
        "user": schemas.UserOut.model_validate(user),
    })


@router.post("/register")
def register(req: schemas.RegisterReq, db: Session = Depends(get_db)):
    if db.query(User).filter_by(username=req.username).first():
        raise param_error("用户名已存在")
    if db.query(User).filter_by(email=req.email).first():
        raise param_error("邮箱已存在")
    user = User(
        username=req.username, email=req.email,
        password_hash=hash_password(req.password),
        role="user", display_name=req.display_name or req.username,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return ok(schemas.UserOut.model_validate(user))


@router.post("/refresh")
def refresh(req: schemas.RefreshReq):
    user_id = decode_token(req.refresh_token, "refresh")
    if not user_id:
        raise param_error("refresh_token 无效")
    return ok({
        "access_token": create_access_token(user_id),
        "token_type": "bearer",
    })


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return ok(schemas.UserOut.model_validate(user))


@router.put("/password")
def change_password(req: schemas.ChangePasswordReq,
                    user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    if not verify_password(req.old_password, user.password_hash):
        raise param_error("原密码错误")
    user.password_hash = hash_password(req.new_password)
    db.commit()
    return ok({})
