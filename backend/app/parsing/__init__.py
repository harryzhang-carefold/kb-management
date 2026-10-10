"""文档解析统一路由 — TXT/MD/HTML 本地解析，其余走 MinerU。

对外入口: parse_document(data, filename, file_type=None) -> (markdown, meta)
兼容旧签名: 见 doc_parser.parse_document()（内部委托本模块）。
"""
from .router import ParseError, detect_file_type, parse_document

__all__ = ["ParseError", "detect_file_type", "parse_document"]
