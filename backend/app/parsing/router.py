"""解析路由 — 扩展名判定 → 本地解析 / MinerU 调用 → 统一 (markdown, meta)。"""
from loguru import logger

from app.core.config import settings
from app.parsing import local_parsers
from app.parsing.mineru_client import MinerUError, parse_with_mineru


class ParseError(Exception):
    """文档解析失败（对外统一异常）。"""


# 扩展名 → file_type
_EXT_MAP = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".pptx": "pptx",
    ".xlsx": "xlsx",
    ".txt": "txt",
    ".md": "md",
    ".markdown": "md",
    ".html": "html",
    ".htm": "html",
    ".jpg": "jpg",
    ".jpeg": "jpg",
    ".png": "png",
    ".bmp": "bmp",
    ".webp": "webp",
    ".tiff": "tiff",
    ".tif": "tiff",
}

# 走 MinerU 的类型（MinerU 官方原生支持）
# PPTX 走本地 python-pptx（PPT 表格多为图片，MinerU 提取效果不稳定）
_MINERU_TYPES = {"docx", "jpg", "png", "bmp", "webp", "tiff"}


def detect_file_type(filename: str):
    """根据扩展名返回 file_type；不支持返回 None；.xls 返回 'xls'（用于友好提示）。"""
    lower = (filename or "").lower()
    for ext, ftype in _EXT_MAP.items():
        if lower.endswith(ext):
            return ftype
    if lower.endswith(".xls"):
        return "xls"  # 不支持，调用方需给出转 xlsx 的提示
    return None


def parse_document(data: bytes, filename: str, file_type: str | None = None) -> tuple[str, dict]:
    """统一解析入口。返回 (markdown 正文, meta 字典)。失败抛 ParseError。"""
    ftype = file_type or detect_file_type(filename)
    if not ftype:
        raise ParseError(f"不支持的文件类型: {filename}")
    if ftype == "xls":
        raise ParseError("不支持 .xls 格式，请另存为 .xlsx 后重新上传")

    try:
        if ftype in ("txt", "md"):
            fn = local_parsers.parse_txt if ftype == "txt" else local_parsers.parse_md
            return fn(data, filename)
        if ftype == "html":
            return local_parsers.parse_html(data, filename)
        if ftype == "pptx":
            return local_parsers.parse_pptx(data, filename)
        if ftype == "xlsx":
            return local_parsers.parse_xlsx(data, filename)
        if ftype == 'pdf':
            from app.knowledge.ingestion import parse_pdf
            return parse_pdf(data, filename)
        if ftype in _MINERU_TYPES:
            try:
                return parse_with_mineru(data, filename, ftype)
            except MinerUError as e:
                raise ParseError(f"MinerU 解析失败（服务不可用或文档无文本内容）: {e}") from e
        raise ParseError(f"不支持的文件类型: {ftype}")
    except ParseError:
        raise
    except Exception as e:
        logger.exception(f"[parsing] failed: {filename} ({ftype})")
        raise ParseError(f"解析 {ftype} 失败: {e}") from e
