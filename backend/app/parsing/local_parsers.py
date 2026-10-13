"""本地解析器 — TXT / MD / HTML / PPTX / XLSX。

输出与 MinerU 路径保持一致：(markdown, meta)。
PPTX 说明：PPT 中的表格多为图片（Office 不支持原生表格对象），本地按
「幻灯片标题 + 备注 + 文本框」提取，图片内容无法提取（已知限制）。
"""
from datetime import datetime

from bs4 import BeautifulSoup


def _meta(source_type: str, source_name: str, **extra) -> dict:
    m = {
        "parse_engine": "local",
        "source_type": source_type,
        "source_name": source_name,
        "parsed_at": datetime.utcnow().isoformat() + "Z",
    }
    m.update(extra)
    return m


def parse_txt(data: bytes, filename: str) -> tuple[str, dict]:
    text = _decode(data)
    if not text.strip():
        raise ValueError("文本内容为空")
    return text.strip(), _meta("txt", filename)


def parse_md(data: bytes, filename: str) -> tuple[str, dict]:
    text = _decode(data)
    if not text.strip():
        raise ValueError("文本内容为空")
    return text.strip(), _meta("md", filename)


def parse_xlsx(data: bytes, filename: str) -> tuple[str, dict]:
    """Extract original cells for text indexing, without inventing business headers.

    The index type is chosen by the upload contract, not this parser. This text
    is discovery material; authoritative cell citations use native evidence.
    """
    from app.knowledge import spreadsheet
    record = spreadsheet.parse(data)
    parts = []
    for sheet in record['sheets']:
        rows = {}
        for cell in sorted(sheet['cells'].values(), key=lambda c: (c['row'], c['column'])):
            value = cell['value']
            if cell['formula'] is not None:
                value = {'formula': cell['formula'], 'cached_value': value,
                         'cached_value_available': cell['cached_value_available']}
            rows.setdefault(cell['row'], {})[cell['coordinate']] = value
        if rows:
            parts.append('## ' + sheet['name'] + '\n\n' +
                         '\n'.join(spreadsheet.encode(row) for row in rows.values()))
    if not parts:
        raise ValueError('XLSX 未提取到任何单元格内容')
    return '\n\n'.join(parts), _meta('xlsx', filename,
        parse_engine='local-openpyxl', parser_version=spreadsheet.PARSER_VERSION,
        sheet_count=len(record['sheets']), sheet_names=[s['name'] for s in record['sheets']])


def parse_html(data: bytes, filename: str) -> tuple[str, dict]:
    html = _decode(data)
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [ln.strip() for ln in text.splitlines()]
    result = "\n".join(ln for ln in lines if ln).strip()
    if not result:
        raise ValueError("HTML 提取文本为空")
    return result, _meta("html", filename)


def parse_pptx(data: bytes, filename: str) -> tuple[str, dict]:
    """PPTX 本地解析：逐页提取 标题/正文/备注，输出 Markdown。"""
    import io
    from pptx import Presentation

    try:
        prs = Presentation(io.BytesIO(data))
    except Exception as e:
        raise ValueError(f"PPTX 解析失败（文件可能已损坏）: {e}")

    parts: list[str] = []
    for idx, slide in enumerate(prs.slides, 1):
        lines: list[str] = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    text = "".join(run.text for run in para.runs).strip()
                    if text:
                        lines.append(text)
            elif shape.has_table:
                # 原生表格（少见，但支持）
                tbl = shape.table
                rows = []
                for r_i, row in enumerate(tbl.rows):
                    cells = [c.text.strip().replace("\n", " ") for c in row.cells]
                    rows.append("| " + " | ".join(cells) + " |")
                    if r_i == 0:
                        rows.append("|" + "---|" * len(cells))
                if rows:
                    lines.append("\n".join(rows))
        # 备注
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                lines.append(f"> 备注: {notes}")

        content = "\n".join(lines).strip()
        if content:
            parts.append(f"## 第 {idx} 页\n\n{content}")

    if not parts:
        raise ValueError("PPTX 未提取到任何文本内容")
    markdown = "\n\n".join(parts)
    return markdown, _meta("pptx", filename, slide_count=len(prs.slides))


def _decode(data: bytes) -> str:
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="ignore")
