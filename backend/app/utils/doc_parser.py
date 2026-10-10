"""文档解析：兼容入口。实际逻辑在 app/parsing/（MinerU + 本地解析）。

保持旧签名 parse_document(data, file_type) -> str，供 workers/tasks.py 使用。
新代码请直接使用 app.parsing.parse_document(data, filename, file_type) -> (markdown, meta)。
"""
from typing import Optional

from loguru import logger

from app.parsing import ParseError  # noqa: F401  (兼容 re-export)
from app.parsing import detect_file_type  # noqa: F401  (兼容 re-export)
from app.parsing import parse_document as _parse_document


def parse_document(data: bytes, file_type: str, filename: str = "document") -> str:
    """旧签名兼容入口：根据文件类型解析为 Markdown 正文。失败抛 ParseError。"""
    try:
        markdown, _meta = _parse_document(data, filename, file_type)
        return markdown
    except ParseError:
        raise
    except Exception as e:
        raise ParseError(f"解析 {file_type} 失败: {e}")
