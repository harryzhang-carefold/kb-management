"""统一响应包裹 + 业务异常。"""
from typing import Any, Generic, Optional, Type, TypeVar

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

T = TypeVar("T")


class APIError(Exception):
    """业务异常，code/message 由 API 契约定义。"""

    def __init__(self, code: int, message: str, http_status: int = 400,
                 data: Optional[Any] = None):
        self.code = code
        self.message = message
        self.http_status = http_status
        self.data = data
        super().__init__(message)


class Ok(BaseModel, Generic[T]):
    code: int = 0
    message: str = "ok"
    data: Optional[T] = None


class PageData(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


# ---- 错误码常量（与 docs/api.md 一致）----
class EC:
    PARAM_ERROR = 40001
    UNAUTHORIZED = 40101
    FORBIDDEN = 40301
    NOT_FOUND = 40401
    CONFLICT = 40901
    FILE_TOO_LARGE = 41301
    INTERNAL = 50001
    SERVICE_UNAVAILABLE = 50301


def err(code: int, message: str, http_status: int = 400, data: Optional[Any] = None) -> APIError:
    return APIError(code, message, http_status, data)


def ok(data: Optional[Any] = None, message: str = "ok") -> dict:
    return {"code": 0, "message": message, "data": data}


def not_found(message: str = "资源不存在") -> APIError:
    return APIError(EC.NOT_FOUND, message, 404)


def unauthorized(message: str = "未认证") -> APIError:
    return APIError(EC.UNAUTHORIZED, message, 401)


def forbidden(message: str = "无权限") -> APIError:
    return APIError(EC.FORBIDDEN, message, 403)


def param_error(message: str = "参数错误") -> APIError:
    return APIError(EC.PARAM_ERROR, message, 400)


def service_unavailable(message: str = "依赖服务不可用") -> APIError:
    return APIError(EC.SERVICE_UNAVAILABLE, message, 503)


async def exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """全局异常处理器：把 APIError / 校验错误 / 未知异常统一包裹。"""
    if isinstance(exc, APIError):
        return JSONResponse(
            status_code=exc.http_status,
            content={"code": exc.code, "message": exc.message, "data": exc.data},
        )
    if isinstance(exc, RequestValidationError):
        return JSONResponse(
            status_code=400,
            content={"code": EC.PARAM_ERROR, "message": "参数错误",
                     "data": {"errors": exc.errors()}},
        )
    # 兜底
    return JSONResponse(
        status_code=500,
        content={"code": EC.INTERNAL, "message": f"服务器内部错误: {exc}", "data": None},
    )
