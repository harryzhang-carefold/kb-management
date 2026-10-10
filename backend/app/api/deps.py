"""FastAPI 认证依赖：从 Bearer token 解析当前用户。"""
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from uuid import UUID

from app.core.database import get_db
from app.core.security import decode_token
from app.core.responses import unauthorized
from app.models import *

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise unauthorized("缺少 Authorization 头")
    user_id = decode_token(credentials.credentials, "access")
    if not user_id:
        raise unauthorized("token 无效或已过期")
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise unauthorized("用户不存在")
    if not user.is_active:
        raise unauthorized("用户已被停用")
    return user


def get_current_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        from app.core.responses import forbidden
        raise forbidden("需要管理员权限")
    return user


def require_kb_access(
    user: User,
    kb: KnowledgeBase,
    min_role: str = "viewer",
) -> None:
    """校验用户对知识库的访问权限。role 等级: viewer < editor < owner。"""
    from app.core.responses import forbidden
    rank = {"viewer": 0, "editor": 1, "owner": 2}
    # admin 直接放行
    if user.role == "admin":
        return
    # owner 直接放行
    if user.id == kb.owner_id:
        return
    member = db_member = None
    # 通过 kb.members 查
    for m in kb.members:
        if m.user_id == user.id:
            if rank[m.role] >= rank[min_role]:
                return
            break
    raise forbidden("无权访问该知识库")
