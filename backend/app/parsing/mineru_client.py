"""MinerU 解析服务客户端 — MinerU 4.x 分层 API（本地 CPU 部署）。

API 流程（/v1 前缀）:
  POST   /v1/uploads                  创建上传会话（JSON: filename/bytes/mime_type）
  PUT    /v1/uploads/{id}/content     上传文件原始字节
  POST   /v1/uploads/{id}/complete    完成上传 → 得到 file_id
  POST   /v1/parse/jobs               提交解析任务（tier: PDF/图片用 basic，Office 用 flash）
  GET    /v1/parse/jobs/{job_id}      轮询任务状态
  GET    /v1/files/{file_id}/content  下载 markdown 输出

健康检查: GET /v1/health
"""
import time
from datetime import datetime
from typing import Optional

import httpx
from loguru import logger

from app.core.config import settings


class MinerUError(Exception):
    """MinerU 服务不可用或解析失败。"""


# 扩展名 → MIME
_MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "bmp": "image/bmp",
    "webp": "image/webp",
    "tiff": "image/tiff",
}

# 纯文本类格式用 flash tier（轻量解析），PDF/图片用 basic（VLM 布局分析）
_FLASH_TYPES = {"docx", "xlsx"}


def _base_url() -> str:
    return settings.mineru_api_url.rstrip("/") + "/v1"


def mineru_health(timeout: float = 5.0) -> dict:
    """健康检查：GET /v1/health，能通即视为 ok。"""
    url = _base_url() + "/health"
    try:
        r = httpx.get(url, timeout=timeout)
        if r.status_code == 200:
            try:
                ver = r.json().get("version", "")
            except Exception:
                ver = ""
            return {"status": "ok", "http_status": r.status_code, "version": ver}
        return {"status": "error", "http_status": r.status_code}
    except Exception as e:
        return {"status": "unreachable", "error": str(e)[:200]}


def parse_with_mineru(data: bytes, filename: str, file_type: str) -> tuple[str, dict]:
    """调用 MinerU 解析，返回 (markdown, meta)。失败抛 MinerUError。"""
    mime = _MIME.get(file_type, "application/octet-stream")
    tier = "flash" if file_type in _FLASH_TYPES else "basic"

    try:
        with httpx.Client(timeout=settings.mineru_timeout_seconds) as client:
            # 1. 创建上传
            r = client.post(_base_url() + "/uploads", json={
                "filename": filename,
                "bytes": len(data),
                "mime_type": mime,
            })
            if r.status_code != 200:
                raise MinerUError(f"创建上传失败 HTTP {r.status_code}: {r.text[:300]}")
            upload_id = r.json()["id"]

            # 2. 上传内容
            r = client.put(_base_url() + f"/uploads/{upload_id}/content", content=data)
            if r.status_code != 200:
                raise MinerUError(f"上传内容失败 HTTP {r.status_code}: {r.text[:300]}")

            # 3. 完成上传
            r = client.post(_base_url() + f"/uploads/{upload_id}/complete")
            if r.status_code != 200:
                raise MinerUError(f"完成上传失败 HTTP {r.status_code}: {r.text[:300]}")
            file_id = r.json()["file"]["id"]

            # 4. 提交解析任务
            r = client.post(_base_url() + "/parse/jobs", json={
                "files": [{"source": {"type": "file_id", "file_id": file_id}}],
                "tier": tier,
                "output_formats": ["markdown"],
            })
            if r.status_code not in (200, 202):
                raise MinerUError(f"提交解析任务失败 HTTP {r.status_code}: {r.text[:300]}")
            job = r.json()
            job_id = job["job_id"]

            # 5. 轮询任务
            t0 = time.time()
            deadline = time.time() + settings.mineru_timeout_seconds
            while time.time() < deadline:
                r = client.get(_base_url() + f"/parse/jobs/{job_id}")
                if r.status_code != 200:
                    raise MinerUError(f"查询任务失败 HTTP {r.status_code}: {r.text[:300]}")
                job = r.json()
                st = job.get("status")
                if st in ("completed", "succeeded"):
                    break
                if st == "failed":
                    errs = [f.get("error") for f in job.get("files", []) if f.get("error")]
                    raise MinerUError(f"解析失败: {errs[:1]}")
                time.sleep(2)
            else:
                raise MinerUError(f"解析超时（{settings.mineru_timeout_seconds}s）")
            elapsed = time.time() - t0

            # 6. 下载 markdown
            md_text = ""
            for f in job.get("files", []):
                of = f.get("output_files") or {}
                md_ref = of.get("markdown")
                if md_ref and md_ref.get("file_id"):
                    r = client.get(_base_url() + f"/files/{md_ref['file_id']}/content")
                    if r.status_code == 200:
                        md_text = r.text
                        break

        markdown = _strip_local_image_refs(md_text or "").strip()
        if not markdown:
            raise MinerUError("MinerU 未返回有效 Markdown（文档可能无文本内容）")

        meta = {
            "parse_engine": f"mineru-{tier}",
            "source_type": file_type,
            "source_name": filename,
            "parse_seconds": round(elapsed, 1),
            "parsed_at": datetime.utcnow().isoformat() + "Z",
        }
        logger.info(f"[mineru] parse done: {filename} tier={tier} {elapsed:.1f}s md_len={len(markdown)}")
        return markdown, meta
    except MinerUError:
        raise
    except Exception as e:
        raise MinerUError(f"MinerU 解析异常: {e}") from e


def _strip_local_image_refs(md: str) -> str:
    """将 ![alt](相对路径) 替换为 [图片: alt]（容器内路径对外不可访问）。

    保留 http(s) 外链与 data: 内联图。
    """
    import re
    def _repl(m: re.Match) -> str:
        alt, src = m.group(1), m.group(2)
        if src.startswith(("http://", "https://", "data:")):
            return m.group(0)
        label = alt.strip() or "图片"
        return f"[图片: {label}]"
    return re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)", _repl, md)
