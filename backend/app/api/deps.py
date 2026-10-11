"""FastAPI 认证依赖：从 Bearer token 解析当前用户。"""
from fastapi import Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from uuid import UUID

from app.core.database import get_db
from app.core.security import decode_token, decode_view_token
from app.core.responses import unauthorized, forbidden
from app.models import *

bearer_scheme = HTTPBearer(auto_error=False)


class ViewTokenContext:
    """view_token 只读上下文（无 User 行，view_only=True）。

    由 get_current_user_or_view_token 在 ?token= 校验通过后构造，
    携带完整 view_token payload（sub=doc_id, kb_id, viewer, ...）。
    require_kb_access 遇 view_only 短路放行（越权已由签发范围锁定）。
    """
    view_only: bool = True

    def __init__(self, payload: dict):
        self.payload = payload
        self.id = str(payload.get("sub"))
        self.role = "viewer"


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


def get_current_user_or_view_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    token: str | None = Query(None, alias="token"),
    db: Session = Depends(get_db),
) -> User | ViewTokenContext:
    """只读端点认证：优先 Bearer JWT（行为与 get_current_user 完全一致）；
    失败则回退 ?token= view_token（无状态 JWT，单文档只读）。

    view_token 校验：
    - 过期/无效 → 401 "链接已过期"
    - 越权（token.kb_id != 路径 kb_id 或 token.sub != 路径 doc_id）→ 403
    - 通过 → ViewTokenContext（view_only=True，无 User 行）
    """
    if credentials is not None and credentials.credentials:
        user_id = decode_token(credentials.credentials, "access")
        if user_id:
            user = db.query(User).filter_by(id=user_id).first()
            if user and user.is_active:
                return user
    if token:
        payload = decode_view_token(token)
        if not payload:
            raise unauthorized("链接已过期")
        path_kb_id = request.path_params.get("kb_id")
        path_doc_id = request.path_params.get("doc_id")
        if path_kb_id is not None and str(payload.get("kb_id")) != str(path_kb_id):
            raise forbidden("无权访问该知识库")
        if path_doc_id is not None and str(payload.get("sub")) != str(path_doc_id):
            raise forbidden("无权访问该文档")
        return ViewTokenContext(payload)
    if credentials is None or not credentials.credentials:
        raise unauthorized("缺少 Authorization 头")
    raise unauthorized("token 无效或已过期")


def get_current_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        from app.core.responses import forbidden
        raise forbidden("需要管理员权限")
    return user


def require_kb_access(
    user: User | ViewTokenContext,
    kb: KnowledgeBase,
    min_role: str = "viewer",
) -> None:
    """校验用户对知识库的访问权限。role 等级: viewer < editor < owner。

    view_only 上下文（view_token）越权范围已由签发时锁定（token.kb_id 与
    路径 kb_id 一致才放行），这里直接放行。
    """
    from app.core.responses import forbidden
    if getattr(user, "view_only", False):
        return
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
