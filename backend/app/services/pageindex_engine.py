"""PageIndex 引擎：无向量、层级树索引 + LLM 推理检索（自实现，不用官方 SDK）。

设计见 00-management-PAGEINDEX_DESIGN.md：
- 建树：LLM（模型名走 settings.pageindex_llm_model，当前 deepseek-flash）从
  document.full_text 生成层级树（2-4 层），
  节点含 title/summary/字符偏移 [start,end)，存 document.meta["pageindex_tree"]。
  失败降级为 heading 规则树（status=degraded）。
- 检索：KB 内所有已建树文档拼 outline → 单次 LLM 联合推理选 top-n 节点 →
  按 full_text[start:end] 切原文，返回与现有 sources 兼容的格式。

不改动现有 ES / embedding / chunk 路径。
"""
import json
import re
import time
import uuid
from datetime import datetime
from typing import Optional

from loguru import logger

from app.core.config import settings
from app.models import Chunk, Document, KnowledgeBase
from app.utils.ai_client import llm_client

# ----------------------------------------------------------------------
# 常量（设计 §4.3）
# ----------------------------------------------------------------------
MAX_DOC_CHARS = 32000        # 建树单次 LLM 输入上限（≈16k tokens）
BUILD_MAX_TOKENS = 32768     # 建树输出预算：推理型模型（deepseek-flash 等）的 reasoning 计入
                             # completion_tokens，8192 时思考可吃满预算 → content 为空 → 建树降级
                             # （实测 484 字文档 1/5 次 finish_reason=length/content=0）
RETRIEVE_MAX_TOKENS = 8192   # 检索选节点输出预算：同为推理型模型，1024 时实测 1/6 次
                             # finish_reason=length → content 为空 → 空结果（不硬凑的兜底不触发）
RETRIEVE_ATTEMPTS = 3        # 检索选节点「空判定」重试上限（BUG-V4-01：推理型模型对同一
                             # prompt 会非确定性地返回 {"selected": []}，temperature=0 亦然；
                             # 实测同一问题空判率 8/12，重试可显著降低但无法归零 → 另有词面降级）
LEX_MIN_MATCHED = 2          # 词面降级判「相关」的最小命中问题词元数
LEX_MIN_COVERAGE = 0.5       # 或问题词元覆盖率下限（短问题兜底：1/1=1.0）
LEX_SCORE_CHARS = 8000       # 词面打分时单节点取用的正文字符上限
LEX_MAX_SCORE = 0.30         # 词面降级命中分值上限（与 LLM 判定命中的典型区间区分）
OUTLINE_BUDGET_CHARS = 24000  # outline 总字符预算（≈6k tokens）；超限则退回「标题+摘要」精简模式
OUTLINE_EXCERPT_CHARS = 150   # outline 每节点附带的正文开头摘录长度（预算内才带）
MAX_OUTLINE_DOCS = 50        # 单次检索参与推理的文档数上限（R5）
MAX_CONTENT_CHARS = 3000     # 单节点引用原文截断
MAX_NODES = 100              # 节点数上限
MAX_DEPTH = 4                # 树深度上限
MAX_CHILDREN = 12            # 每层节点数上限（软约束，校验时记录不硬失败）

TREE_KEY = "pageindex_tree"
STATUS_KEY = "pageindex_status"  # none / building / ok / degraded / failed

# ----------------------------------------------------------------------
# Prompts（设计 §3）
# ----------------------------------------------------------------------
BUILD_SYSTEM = """你是文档结构分析器。你的任务是为一篇长文档生成层级树索引（类似"目录+摘要"）。
严格遵守：
1. 层级 2-4 层，每层不超过 12 个节点；
2. 每个节点必须给出 start/end 字符偏移：start 是该节点正文起始字符位置（从 0 计），
   end 是该节点正文结束字符位置（不含）；父区间必须包含子区间，同层子区间不重叠且按顺序排列；
3. 叶子节点覆盖 300-3000 字符；整棵树覆盖文档全部正文；
4. title 用原文标题（无标题处自拟简短标题），summary ≤80 字；
5. 只输出 JSON，不输出任何解释文字。"""

BUILD_USER = """请为以下文档生成树索引 JSON。
输出格式：
{{"root": {{"node_id":"n1","title":"...","summary":"...","start":0,"end":<全文长度>,
  "children":[ {{"node_id":"n1.1","title":"...","summary":"...","start":..,"end":..,"children":[]}} ]}}}}

全文长度：{chars}
文档开始：
<<<DOC_START>>>
{full_text}
<<<DOC_END>>>"""

RETRIEVE_SYSTEM = """你是知识库检索器。给定多个文档的树索引目录（含 doc_id、节点编号、标题、摘要、字符区间，
部分节点附有正文开头「摘录」）和一个用户问题，选出最相关的节点。
严格遵守：
1. 只从给定节点中选择，node_id 必须原样引用，不得杜撰；
2. 选 1-{top_n} 个节点，按相关度降序；
3. 每个节点给出 relevance 分数（0-1 之间的小数，两位）；
4. 摘录是节点正文开头的一小段（**已截断，非全文**）：若问题所问的细节（术语、编号、
   口令、数值等）出现在某节点的摘录里，优先选该节点并给高分（0.6 以上）；
5. 摘录未覆盖问题细节时，只要问题与某节点的**主题**相关，仍应选中该节点并给出分数
   （相关性较弱可给低分，如 0.2-0.5），不要因为查不到细节词就返回空数组；
6. 只有当问题与所有节点的主题都明显无关（例如问的是另一个领域）时才返回空数组；
7. 只输出 JSON。"""

RETRIEVE_RETRY_HINT = """上一次返回了空数组。请复核上面的目录：摘录只是节点正文的开头一小段
（已截断），若问题所问的细节出现在某节点摘录里，就选该节点并给高分；否则只要问题与某节点的
**主题**相关，也应按上述规则选出最相关的 1-{top_n} 个节点（相关性弱可给低分）；
仅当问题与所有节点主题都明显无关时，才再次返回空数组。仍然只输出 JSON。"""

RETRIEVE_USER = """用户问题：{question}

文档目录：
{outline_lines}

输出格式：
{{"selected": [{{"doc_id":"...","node_id":"...","relevance":0.87}}]}}"""


# ----------------------------------------------------------------------
# 工具函数
# ----------------------------------------------------------------------

def _extract_json(text: str) -> dict:
    """从 LLM 输出提取首个 JSON 对象（容错：前后多余文字 / markdown 代码块）。"""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        pass
    # 提取首个 {...} 块（括号配对扫描，避免跨串误匹配）
    start = text.find("{")
    if start < 0:
        raise ValueError("LLM 输出不含 JSON 对象")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(text[start:i + 1])
    raise ValueError("LLM 输出 JSON 不完整")


def _validate_tree(tree: dict, full_len: int) -> list[str]:
    """校验树结构（设计 §3.1 输出后校验）。返回错误列表，空列表=通过。"""
    errors: list[str] = []
    root = tree.get("root")
    if not isinstance(root, dict):
        return ["缺少 root 节点"]

    node_count = 0
    tolerance = max(50, int(full_len * 0.05))

    def walk(node: dict, depth: int, parent: Optional[tuple[int, int]], path: str):
        nonlocal node_count
        node_count += 1
        if node_count > MAX_NODES:
            errors.append(f"节点数 {node_count} 超上限 {MAX_NODES}")
            return
        if depth > MAX_DEPTH:
            errors.append(f"深度 {depth} 超上限 {MAX_DEPTH}")
            return
        title = node.get("title")
        if not isinstance(title, str) or not title.strip():
            errors.append(f"{path}: title 缺失")
        summary = node.get("summary")
        if not isinstance(summary, str):
            errors.append(f"{path}: summary 缺失")
        start, end = node.get("start"), node.get("end")
        if not isinstance(start, int) or not isinstance(end, int):
            errors.append(f"{path}: start/end 不是整数")
            return
        if end <= start:
            errors.append(f"{path}: end({end}) <= start({start})")
            return
        if start < 0 or end > full_len + tolerance:
            errors.append(f"{path}: 区间 [{start},{end}] 越界（全文 {full_len} 字符）")
        if parent is not None:
            ps, pe = parent
            if start < ps or end > pe:
                errors.append(f"{path}: 区间 [{start},{end}] 超出父区间 [{ps},{pe}]")
        children = node.get("children", [])
        if not isinstance(children, list):
            errors.append(f"{path}: children 不是数组")
            return
        if len(children) > MAX_CHILDREN:
            errors.append(f"{path}: 子节点 {len(children)} 个超软上限 {MAX_CHILDREN}")
        prev_end = None
        for ci, child in enumerate(children):
            if not isinstance(child, dict):
                errors.append(f"{path}.{ci}: 子节点不是对象")
                continue
            c_start, c_end = child.get("start"), child.get("end")
            if isinstance(c_start, int) and isinstance(c_end, int):
                if prev_end is not None and c_start < prev_end:
                    errors.append(f"{path}.{ci}: 子区间与前一子区间重叠")
                prev_end = c_end
            walk(child, depth + 1, (start, end), f"{path}.{ci}")

    walk(root, 1, None, "n1")
    # root 覆盖度：start≈0、end≈full_len（±5%）
    rs, re_ = root.get("start"), root.get("end")
    if not isinstance(rs, int) or not isinstance(re_, int):
        errors.append("root 缺少 start/end")
    else:
        if rs > tolerance:
            errors.append(f"root.start={rs} 应≈0")
        if abs(re_ - full_len) > tolerance:
            errors.append(f"root.end={re_} 与全文长度 {full_len} 偏差超 5%")
    return errors


def _summarize(text: str, limit: int = 80) -> str:
    """摘要兜底：取节内首个非空行前 limit 字。"""
    for line in (text or "").splitlines():
        line = line.strip().lstrip("#|> \t").strip()
        if line:
            return line[:limit]
    return (text or "").strip()[:limit]


def _first_content(text: str, limit: int = 80) -> str:
    """摘要兜底：取首个非标题/分隔/表格行的正文前 limit 字。"""
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if re.match(r"^#{1,6}\s", line) or line.startswith("---") or line.startswith("|"):
            continue
        cleaned = re.sub(r"[*_`>]", "", line).strip()
        if cleaned:
            return cleaned[:limit]
    return _summarize(text, limit)


def _heading_degraded_tree(full_text: str) -> dict:
    """R2 降级树：按 Markdown heading 规则生成 2-3 层树（无 LLM）。

    规则：首个 `#` 视为文档标题（根），其后的 `#` 为一级章节、`##` 为二级；
    无 `#` 时 `##` 提升为一级。偏移相对 full_text（含 front-matter）。
    """
    import app.services.chunker as chunker  # 复用 heading 识别约定
    body = chunker._strip_front_matter(full_text)
    offset = len(full_text) - len(body)  # front-matter 占位偏移

    # 行起始字符偏移（body 内，逐行含换行累计）
    lines = body.splitlines()
    line_offsets: list[int] = []
    pos = 0
    for ln in lines:
        line_offsets.append(pos)
        pos += len(ln) + 1

    heads: list[tuple[int, int, str, int]] = []  # (line_idx, level, title, char_offset)
    for i, ln in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.*)", ln.strip())
        if m:
            heads.append((i, len(m.group(1)), m.group(2).strip(), line_offsets[i]))

    # 文档标题判定：
    # - 第一个 heading 是 h1，且其后紧邻的不是同级 h1 → 它是文档标题（其后为章节）
    #   （即：单一 h1 + h2 子节，或 h1 后直接 h2/正文）
    # - 文首 h1 紧跟另一个 h1 → 文首 h1 是章节（无标题行），首段正文作标题
    doc_title = _first_content(full_text[:300]) or "文档"
    section_heads: list[tuple[int, int, str, int]] = []
    title_idx: Optional[int] = None
    if heads:
        if len(heads) > 1 and heads[0][1] == 1 and heads[1][1] != 1:
            title_idx = 0
        if title_idx is not None:
            doc_title = heads[title_idx][2]
            section_heads = [h for j, h in enumerate(heads) if j != title_idx]
        if not section_heads:
            section_heads = list(heads)

    # 归一化层级：最小 level 视为一级
    if section_heads:
        min_lv = min(lv for _, lv, _, _ in section_heads)
        l1 = [(li, t, off) for li, lv, t, off in section_heads if lv == min_lv]
        l2 = [(li, t, off) for li, lv, t, off in section_heads if lv == min_lv + 1]
    else:
        l1, l2 = [], []

    def char_of(li: int) -> int:
        return offset + line_offsets[li] if li < len(line_offsets) else len(full_text)

    def make_node(node_id: str, title: str, start: int, end: int, children: list) -> dict:
        content_seg = full_text[max(start, 0):min(end, len(full_text))]
        return {
            "node_id": node_id,
            "title": title,
            "summary": _first_content(content_seg),
            "start": start,
            "end": end,
            "children": children,
        }

    children: list[dict] = []
    if l1:
        for idx, (li, title, off) in enumerate(l1):
            next_li = l1[idx + 1][0] if idx + 1 < len(l1) else len(lines)
            seg_end = char_of(next_li) if next_li < len(lines) else len(full_text)
            if seg_end - off < 50:
                continue
            sub_children = []
            h2_in = [x for x in l2 if li < x[0] < next_li]
            for j2, (li2, t2, off2) in enumerate(h2_in):
                next_li2 = h2_in[j2 + 1][0] if j2 + 1 < len(h2_in) else next_li
                seg2_end = char_of(next_li2) if next_li2 < len(lines) else seg_end
                if seg2_end - off2 < 50:
                    continue
                sub_children.append(make_node(
                    f"n1.{idx + 1}.{j2 + 1}", t2, off2, min(seg2_end, seg_end), []))
            children.append(make_node(f"n1.{idx + 1}", title, off, seg_end, sub_children))
    if not children:
        # 无 heading：整篇按 3000 字符切叶子
        step = 3000
        for i in range(0, max(len(body), 1), step):
            seg_start = offset + i
            seg_end = min(seg_start + step, len(full_text))
            if seg_end <= seg_start:
                break
            children.append(make_node(
                f"n1.{i // step + 1}", _first_content(body[i:i + 300], 30) or f"段落 {i // step + 1}",
                seg_start, seg_end, []))

    root = {
        "node_id": "n1",
        "title": doc_title[:80],
        "summary": _first_content(body[:500]),
        "start": 0,
        "end": len(full_text),
        "children": children,
    }
    return root


def _count_nodes(node: dict) -> int:
    n = 1
    for c in node.get("children", []):
        n += _count_nodes(c)
    return n


def _one_line(text: str, limit: int) -> str:
    """压成单行并截断（outline 每节点一行的排版约束）。"""
    return re.sub(r"\s+", " ", (text or "").strip())[:limit]


def _outline_lines(doc_id: str, root: dict, full_text: str = "",
                   excerpt_chars: int = 0) -> list[str]:
    """把树扁平成 outline 行（每节点一行；摘要截 50 字）。

    excerpt_chars > 0 时额外附「正文开头摘录」：摘要只有 50 字且常被截在句中，
    选节点时缺少实质信号（BUG-V4-01：问题细节在正文、摘要里查不到 → 模型倾向判空
    或选错节点）。摘录受调用侧总预算约束（`OUTLINE_BUDGET_CHARS`），超预算时调用方
    退回 excerpt_chars=0 的精简模式。
    """
    lines: list[str] = []

    def walk(node: dict):
        nid = node.get("node_id", "?")
        title = (node.get("title") or "").strip().replace("\n", " ")
        summary = (node.get("summary") or "").strip().replace("\n", " ")[:50]
        s, e = node.get("start", 0), node.get("end", 0)
        line = f"[{nid}] doc={doc_id[:8]} | {title} | {summary} | {s}-{e}"
        if excerpt_chars:
            excerpt = _one_line((full_text or "")[max(0, int(s)):max(0, int(e))], excerpt_chars)
            if excerpt:
                line += f" | 摘录: {excerpt}"
        lines.append(line)
        for c in node.get("children", []):
            walk(c)

    walk(root)
    return lines


def _find_node(root: dict, node_id: str) -> Optional[dict]:
    """按 node_id 精确查找；失败时前缀匹配（n1.1 → 命中的最深节点）。"""
    found: list[dict] = []

    def walk(node: dict):
        if node.get("node_id") == node_id:
            found.append(node)
        for c in node.get("children", []):
            walk(c)

    walk(root)
    if found:
        return found[0]
    # 前缀匹配：node_id 是某节点前缀（n1.1 命中 n1.1.1 的父 = n1.1 自身不存在时取 n1）
    cands = []

    def walk2(node: dict):
        nid = node.get("node_id", "")
        if node_id.startswith(nid) and nid != node_id:
            cands.append(node)
        for c in node.get("children", []):
            walk2(c)

    walk2(root)
    # 取最长前缀（最深）的候选
    if cands:
        cands.sort(key=lambda n: len(n.get("node_id", "")), reverse=True)
        return cands[0]
    return None


def _walk_nodes(root: dict) -> list[dict]:
    """前序遍历整棵树的节点（自含顺序：父在子前）。"""
    out: list[dict] = []

    def walk(node: dict):
        out.append(node)
        for c in node.get("children", []):
            walk(c)

    walk(root)
    return out


def _lex_tokens(text: str) -> set[str]:
    """词面词元：CJK 连续段的 2-gram + 拉丁/数字词（≥2 字符）。

    仅用于「LLM 判定为空」时判断问题与该 KB 节点文本是否存在实质词面重叠，
    不参与正常检索排序（正常排序由 LLM 语义判定负责）。
    """
    text = (text or "").lower()
    toks: set[str] = set()
    for seg in re.findall(r"[\u4e00-\u9fff]+", text):
        for i in range(len(seg) - 1):
            toks.add(seg[i:i + 2])
    for word in re.findall(r"[a-z0-9]{2,}", text):
        toks.add(word)
    return toks


def _lexical_rank(filtered: list[tuple[Document, dict]],
                  question: str) -> tuple[list[tuple], bool]:
    """对全部候选节点按「问题词元在节点正文中的覆盖率」打分，降序返回。

    返回 (ranked, related)：
      ranked 元素 = (coverage, matched, 节点编号长度, doc, tree, node)（matched=0 的节点不入列）；
      related = 是否判为「问题与本 KB 的 pageindex 节点实质相关」——
                matched ≥ LEX_MIN_MATCHED 或 coverage ≥ LEX_MIN_COVERAGE。

    用途（BUG-V4-01）：LLM 返回空数组时区分两种成因 ——
      related=True  → 判为 LLM 漏检（false empty）→ 按词面降级返回，不静默空结果；
      related=False → 判为真的无相关节点 → 维持 0 命中（保持既有 0 命中语义与文案）。
    """
    q_toks = _lex_tokens(question)
    ranked: list[tuple] = []
    if not q_toks:
        return ranked, False
    for d, tree in filtered:
        full_text = d.full_text or ""
        for node in _walk_nodes(tree["root"]):
            start = int(node.get("start", 0))
            end = int(node.get("end", 0))
            seg = full_text[max(0, start):max(0, end)][:LEX_SCORE_CHARS]
            matched = len(q_toks & _lex_tokens(seg))
            if matched <= 0:
                continue
            coverage = matched / len(q_toks)
            ranked.append((coverage, matched, len(str(node.get("node_id", ""))), d, tree, node))
    # 覆盖率降序 → 命中数降序 → 节点更具体（编号更长）优先（同文档同覆盖率时取更深节点）
    ranked.sort(key=lambda x: (-x[0], -x[1], -x[2]))
    related = bool(ranked) and (ranked[0][1] >= LEX_MIN_MATCHED
                                or ranked[0][0] >= LEX_MIN_COVERAGE)
    return ranked, related


# ----------------------------------------------------------------------
# 建树
# ----------------------------------------------------------------------

def _renumber(node: dict, prefix: str, is_root: bool) -> dict:
    """把 LLM 生成的 n1/n1.1/… 编号重映射到 prefix 前缀。

    LLM 根节点 "n1" → prefix；子节点 "n1.k" → prefix.k；"n1.k.m" → prefix.k.m。
    """
    nid = node.get("node_id", "n1")
    if is_root:
        new_id = prefix
    else:
        # LLM 侧编号形如 n1 / n1.1 / n1.1.2（相对根）。取相对段时**去掉前导点**，
        # 否则 "n1.1" → rel=".1" → "n1..1"（历史缺陷：outline 与 location.node_id
        # 出现双点编号；检索按串精确匹配故不影响命中，但引用展示/外部引用契约脏）。
        rel = nid[2:].lstrip(".") if nid.startswith("n1") else ""
        new_id = f"{prefix}.{rel}" if rel else prefix
    return {
        "node_id": new_id,
        "title": node.get("title", ""),
        "summary": node.get("summary", ""),
        "start": node.get("start", 0),
        "end": node.get("end", 0),
        "children": [_renumber(c, new_id, False) for c in node.get("children", [])],
    }


def _llm_build_piece(piece: str, base_offset: int, node_prefix: str) -> dict:
    """对单片正文调 LLM 建树，返回该片根节点（偏移已平移到全文坐标）。

    node_prefix: 该片根节点在整棵树中的编号（如 "n1.2"）。
    """
    user_prompt = BUILD_USER.format(chars=len(piece), full_text=piece)
    messages = [
        {"role": "system", "content": BUILD_SYSTEM},
        {"role": "user", "content": user_prompt},
    ]

    def _attempt(msgs: list[dict]) -> tuple[dict, dict]:
        """一次调用 + 解析；输出为空/不可解析/缺 root 都抛异常。"""
        raw = llm_client.chat(
            msgs, temperature=0.0, max_tokens=BUILD_MAX_TOKENS,
            timeout=settings.pageindex_build_timeout, json_mode=True,
        )
        data = _extract_json(raw)
        root = data.get("root")
        if not isinstance(root, dict):
            raise ValueError("建树 LLM 输出缺少 root")
        return data, root

    # 首次调用：解析失败（如输出被预算截断 → content 为空）与结构校验失败同样触发一次重试
    data, root, errors = None, None, []
    try:
        data, root = _attempt(messages)
        errors = _validate_tree(data, len(piece))
    except Exception as exc:
        errors = [f"上一次输出无法解析为树 JSON（{exc}）"]

    if errors:
        retry_user = user_prompt + (
            "\n\n上一次输出有如下问题，请修正后重新输出：\n- "
            + "\n- ".join(errors[:5])
        )
        try:
            data2, root2 = _attempt(messages[:1] + [{"role": "user", "content": retry_user}])
            if not _validate_tree(data2, len(piece)):
                data, root = data2, root2
        except Exception:
            if root is None:
                raise  # 两次都没拿到可用 JSON → 交由上层降级

    # 平移偏移 + 重编号节点
    assert isinstance(root, dict)  # 两次都没拿到可用 JSON 时已在上面 raise
    renumbered = _renumber(root, node_prefix, is_root=True)
    renumbered["start"] = base_offset + int(renumbered.get("start", 0))
    renumbered["end"] = base_offset + int(renumbered.get("end", 0))

    def translate(node: dict) -> None:
        for c in node.get("children", []):
            c["start"] = base_offset + int(c.get("start", 0))
            c["end"] = base_offset + int(c.get("end", 0))
            translate(c)

    translate(renumbered)
    return renumbered


def _split_by_heading(full_text: str, limit: int = MAX_DOC_CHARS) -> list[tuple[int, str]]:
    """按 heading 分片，每片 ≤ limit 字符。返回 [(start, piece_text)]。

    无 heading 或单片即够时返回 [(0, full_text)]。
    """
    if len(full_text) <= limit:
        return [(0, full_text)]
    lines = full_text.split("\n")
    # heading 行位置（字符偏移）
    boundaries = [0]
    pos = 0
    for ln in lines:
        if re.match(r"^#{1,3}\s", ln.strip()):
            if pos > 0:
                boundaries.append(pos)
        pos += len(ln) + 1
    if len(boundaries) <= 1:
        # 无 heading：按 limit 硬切
        pieces = []
        for i in range(0, len(full_text), limit):
            pieces.append((i, full_text[i:i + limit]))
        return pieces
    # 把 heading 边界聚成 ≤ limit 的段
    pieces: list[tuple[int, str]] = []
    seg_start = 0
    for b in boundaries[1:] + [len(full_text)]:
        if b - seg_start > limit:
            # 找 seg_start..b 范围内最接近 limit 的边界
            cut = max(x for x in boundaries if seg_start < x <= b and x - seg_start <= limit)
            pieces.append((seg_start, full_text[seg_start:cut]))
            seg_start = cut
    if seg_start < len(full_text):
        pieces.append((seg_start, full_text[seg_start:]))
    return pieces


def build_tree_index(document: Document, db) -> dict:
    """生成树并写入 document.meta['pageindex_tree']，返回树 meta。

    流程：分片 → 逐片 LLM 建树 → 合并 → 校验 → 降级兜底。
    document 必须已加载 full_text。db 用于最终 commit（调用方负责会话）。
    """
    t0 = time.time()
    full_text = document.full_text or ""
    if not full_text.strip():
        raise ValueError("full_text 为空，无法建树")

    pieces = _split_by_heading(full_text)
    root_children: list[dict] = []
    status = "ok"
    try:
        for i, (start, piece) in enumerate(pieces):
            prefix = f"n1.{i + 1}" if len(pieces) > 1 else "n1"
            child = _llm_build_piece(piece, start, prefix)
            root_children.append(child)
    except Exception as e:
        logger.warning(f"[pageindex] LLM 建树失败（doc={document.id}）: {e} → 降级 heading 规则树")
        root = _heading_degraded_tree(full_text)
        status = "degraded"
        meta = _assemble_meta(root, full_text, t0, status, len(pieces))
        doc_meta = dict(document.meta or {})
        doc_meta[TREE_KEY] = meta
        doc_meta[STATUS_KEY] = status
        document.meta = doc_meta
        db.commit()
        return meta

    # 组装根节点：单片时 LLM 返回的即整棵树（child 编号 n1），直接复用
    if len(pieces) == 1:
        root = root_children[0]
        root["start"] = 0
        root["end"] = len(full_text)
    else:
        root = {
            "node_id": "n1",
            "title": (document.filename or "文档")[:80],
            "summary": _summarize(full_text[:300]),
            "start": 0,
            "end": len(full_text),
            "children": root_children,
        }

    # 整树结构校验（只查硬性错误：越界/重叠/超节点数/超深度；
    # 分片合并树的覆盖度允许片段间有空隙）
    if status == "ok":
        errors = _validate_tree({"root": root}, len(full_text))
        hard = [e for e in errors
                if ("越界" in e or "超出父区间" in e or "重叠" in e
                    or "超上限" in e or "end(" in e
                    or "title 缺失" in e or "children 不是数组" in e)]
        if hard:
            logger.warning(f"[pageindex] 合并树校验未通过: {hard[:3]} → 降级")
            root = _heading_degraded_tree(full_text)
            status = "degraded"

    meta = _assemble_meta(root, full_text, t0, status, len(pieces))
    doc_meta = dict(document.meta or {})
    doc_meta[TREE_KEY] = meta
    doc_meta[STATUS_KEY] = status
    document.meta = doc_meta
    db.commit()
    return meta


def _assemble_meta(root: dict, full_text: str, t0: float, status: str, piece_count: int) -> dict:
    return {
        "version": 1,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "model": settings.pageindex_llm_model,
        "full_text_chars": len(full_text),
        "node_count": _count_nodes(root),
        "build_ms": int((time.time() - t0) * 1000),
        "status": status,
        "piece_count": piece_count,
        "root": root,
    }


def rebuild_tree_index(document: Document, db) -> dict:
    """强制重建：先清旧树再建（rebuild API / reparse 钩子）。"""
    doc_meta = dict(document.meta or {})
    doc_meta.pop(TREE_KEY, None)
    doc_meta[STATUS_KEY] = "building"
    document.meta = doc_meta
    db.commit()
    return build_tree_index(document, db)


# ----------------------------------------------------------------------
# 检索
# ----------------------------------------------------------------------

def retrieve(kb_id: str, question: str, top_n: int = 5,
             filters: Optional[dict] = None, db=None) -> tuple[list[dict], int, Optional[dict]]:
    """KB 级 LLM 推理检索。

    返回 (results, took_ms, extra)。results 元素格式与设计 §4.2 一致：
    {chunk_id, document_id, filename, chunk_index, content, score,
     match_type='pageindex', metadata}
    extra: {docs_considered, docs_total, error?}
    db: 可选 Session；为 None 时自建（检索端点已有会话时传入避免嵌套）。
    """
    t0 = time.time()
    own_session = db is None
    if own_session:
        from app.core.database import SessionLocal
        db = SessionLocal()
    try:
        # 1. 查 KB 下"按文档选择了 pageindex 索引"且已建树的文档；
        #    index_type / pageindex_status 存于 meta JSONB，Python 侧过滤
        #    （文档量小，无性能问题）。v2：按文档二选一，不再看 KB 级开关。
        docs = (db.query(Document)
                .filter(Document.kb_id == kb_id, Document.is_deleted.is_(False),
                        Document.full_text.isnot(None))
                .order_by(Document.indexed_at.desc().nullslast())
                .all())
        filtered = []
        file_type = (filters or {}).get("file_type")
        for d in docs:
            meta = d.meta or {}
            if meta.get("index_type") != "pageindex":
                continue
            tree = meta.get(TREE_KEY)
            if not tree or tree.get("status") not in ("ok", "degraded"):
                continue
            if file_type and d.file_type != file_type:
                continue
            if tree.get("full_text_chars") != len(d.full_text or ""):
                # R8：reparse 后偏移失效 → 标 stale，仍参与（切片时兜底丢弃越界节点）
                tree = {**tree, "stale": True}
            filtered.append((d, tree))

        extra: dict = {"docs_total": len(docs), "docs_considered": len(filtered)}
        if not filtered:
            # v2 需求 4：对无 pageindex 索引的文档做 pageindex 检索 →
            # 空结果 + 提示，不静默回退 ES
            extra["empty_reason"] = "no_pageindex_docs"
            extra["message"] = (
                "该知识库下没有使用 PageIndex 索引的文档"
                "（上传时需选择 PageIndex 索引方式），请更换检索方式或重新上传文档。")
            return [], int((time.time() - t0) * 1000), extra

        # R5：文档数 > 50 → 取最近 50 个
        if len(filtered) > MAX_OUTLINE_DOCS:
            filtered = filtered[:MAX_OUTLINE_DOCS]
            extra["docs_considered"] = MAX_OUTLINE_DOCS

        # 2. 拼 outline（优先带正文摘录；超总预算则退回「标题+摘要」精简模式）
        doc_index: dict[str, tuple[Document, dict]] = {}
        for d, tree in filtered:
            doc_index[str(d.id)] = (d, tree)

        def _build_outline(with_excerpt: bool) -> list[str]:
            lines: list[str] = []
            for d, tree in filtered:
                lines.extend(_outline_lines(
                    str(d.id), tree["root"], d.full_text or "",
                    OUTLINE_EXCERPT_CHARS if with_excerpt else 0))
            return lines

        outline_lines = _build_outline(True)
        if len("\n".join(outline_lines)) > OUTLINE_BUDGET_CHARS:
            outline_lines = _build_outline(False)
            extra["outline_mode"] = "title_summary"
        else:
            extra["outline_mode"] = "with_excerpt"
        extra["outline_lines"] = len(outline_lines)

        # 3. LLM 联合推理选节点（不可解析/空判定 → 重试 → 词面降级 → 区分文案）
        #    背景（BUG-V4-01）：推理型模型对**同一** prompt 会非确定性地
        #      (a) 返回 {"selected": []}（temperature=0 亦然，实测 8/12）；
        #      (b) 返回无法在本 KB 树中解析的 doc_id/node_id（被全部丢弃 → 同样是 0 命中）。
        #    旧实现把两者都当合法终态 → 静默 0 命中、无重试、无兜底。现为：
        #    「可解析结果为空」先做词面相关性裁定，再决定重试 / 词面降级 / 维持 0 命中。
        def _postprocess(selected_items: list[dict]) -> tuple[list[dict], list[dict]]:
            """把 LLM 的选择转成结果；返回 (results, unresolved)。"""
            out: list[dict] = []
            bad: list[dict] = []
            seen = set()
            for sel in selected_items:
                if not isinstance(sel, dict):
                    continue
                doc_id = str(sel.get("doc_id", ""))
                node_id = str(sel.get("node_id", ""))
                relevance = sel.get("relevance", 0.0)
                try:
                    relevance = float(relevance)
                except (TypeError, ValueError):
                    relevance = 0.0
                relevance = max(0.0, min(1.0, relevance))
                hit = doc_index.get(doc_id)
                if not hit:
                    # doc_id 可能是短前缀（outline 里是 doc={8位}）
                    for k in doc_index:
                        if k.startswith(doc_id):
                            hit = doc_index[k]
                            doc_id = k
                            break
                if not hit:
                    bad.append({"doc_id": doc_id, "node_id": node_id, "reason": "doc_id_unknown"})
                    continue
                d, tree = hit
                node = _find_node(tree["root"], node_id)
                if not node:
                    bad.append({"doc_id": doc_id, "node_id": node_id, "reason": "node_id_unknown"})
                    continue
                key = (doc_id, node_id)
                if key in seen:
                    continue
                seen.add(key)
                out.append(_build_result(d, tree, node, relevance))
            out.sort(key=lambda r: r["score"], reverse=True)
            return out[:top_n], bad

        base_messages = [
            {"role": "system", "content": RETRIEVE_SYSTEM.format(top_n=top_n)},
            {"role": "user", "content": RETRIEVE_USER.format(
                question=question, outline_lines="\n".join(outline_lines))},
        ]
        attempts_cfg = max(1, int(settings.pageindex_retrieve_attempts or RETRIEVE_ATTEMPTS))
        results: list[dict] = []
        selected: list[dict] = []
        unresolved: list[dict] = []
        lex_ranked: list[tuple] = []
        lex_related = False
        llm_error: Optional[str] = None
        attempts_used = 0
        for attempt in range(1, attempts_cfg + 1):
            attempts_used = attempt
            messages = list(base_messages)
            if attempt > 1:
                messages.append({"role": "user",
                                 "content": RETRIEVE_RETRY_HINT.format(top_n=top_n)})
            try:
                raw = llm_client.chat(
                    messages, temperature=0.0, max_tokens=RETRIEVE_MAX_TOKENS,
                    timeout=settings.pageindex_retrieve_timeout, json_mode=True,
                )
                data = _extract_json(raw)
                sel = data.get("selected", []) if isinstance(data, dict) else []
                selected = [s for s in sel if isinstance(s, dict)] if isinstance(sel, list) else []
                llm_error = None
                results, unresolved = _postprocess(selected)
                if selected and not results:
                    # 选中了但一个都解析不出来（doc_id/node_id 不可用）→ 记为无效尝试
                    llm_error = (f"LLM 选中的 {len(unresolved)} 个节点无法在本 KB 树中解析"
                                 f"（{unresolved[:3]}）")
                    logger.warning(f"[pageindex] attempt {attempt}/{attempts_cfg} "
                                   f"选中但不可解析 kb={kb_id}: {unresolved[:3]}")
            except Exception as exc:  # 超时/网络/解析失败 → 与「空判定」同一重试路径
                selected, results, unresolved = [], [], []
                llm_error = str(exc)
                logger.warning(f"[pageindex] retrieve attempt {attempt}/{attempts_cfg} "
                               f"失败 kb={kb_id}: {exc}")
            if results:
                break
            # 无可用结果：先裁定词面相关性（每次检索只算一次）
            if not lex_ranked:
                lex_ranked, lex_related = _lexical_rank(filtered, question)
            if not lex_related:
                # 问题与所有节点主题都无关 → 不再重试（保持既有 0 命中语义与 auto F6 文案）
                break

        extra["attempts"] = attempts_used
        extra["llm_empty"] = not selected
        if unresolved:
            extra["unresolved_selected"] = unresolved[:5]
        if llm_error:
            extra["llm_error"] = llm_error

        # 4. 无可用结果：词面相关 → 降级返回（不漏检）；确实无关 → 0 命中 + 区分文案
        if not results:
            if lex_related:
                fallback: list[dict] = []
                for coverage, matched, _nid_len, d, tree, node in lex_ranked[:top_n]:
                    fallback.append(_build_result(
                        d, tree, node, min(LEX_MAX_SCORE, round(coverage, 2)),
                        selected_by="lexical_fallback",
                        lex_coverage=round(coverage, 3), lex_matched=matched))
                extra["fallback"] = {
                    "reason": "llm_empty_but_lexically_related",
                    "attempts": attempts_used,
                    "lex_coverage": round(lex_ranked[0][0], 3),
                    "lex_matched": lex_ranked[0][1],
                    "llm_error": llm_error,
                }
                logger.warning(
                    f"[pageindex] LLM {attempts_used} 次均无可解析结果但词面相关 → 词面降级 "
                    f"kb={kb_id} docs={len(filtered)} coverage={lex_ranked[0][0]:.2f} "
                    f"matched={lex_ranked[0][1]} llm_error={llm_error}")
                return fallback, int((time.time() - t0) * 1000), extra
            extra["empty_reason"] = "no_node_selected"
            extra["message"] = (
                f"该知识库已有 {len(filtered)} 篇 PageIndex 文档，但本次未选中任何相关节点。"
                "请换一种问法（树索引对文档标题与小节更敏感），或对相关文档重建 PageIndex 索引。")
            logger.info(f"[pageindex] 0 命中 kb={kb_id} docs={len(filtered)} "
                        f"attempts={attempts_used} llm_error={llm_error} reason=no_node_selected")
            return [], int((time.time() - t0) * 1000), extra

        # 5. 命中：返回结果（结果后处理已在 _postprocess 内完成，含排序与截断）
        return results, int((time.time() - t0) * 1000), extra
    except Exception as e:
        logger.error(f"[pageindex] retrieve failed kb={kb_id}: {e}")
        # R1：检索阶段 LLM 失败直接返回空结果 + error 标记，不回退 ES
        return [], int((time.time() - t0) * 1000), {"error": str(e)}
    finally:
        if own_session:
            db.close()


def _first_chunk_anchor(db, document: Document) -> tuple:
    """节点区间内第一个已存在 chunk（找不到 → chunk_index=0 的 chunk）作溯源锚点。"""
    rows = (db.query(Chunk)
            .filter(Chunk.document_id == document.id)
            .order_by(Chunk.chunk_index.asc())
            .limit(200)
            .all())
    if not rows:
        # 极端：无 chunk（chunk 索引失败但 pageindex 建好了）→ 用 doc id 兜底
        return str(document.id), 0
    first = rows[0]
    return str(first.id), first.chunk_index


def _build_result(doc: Document, tree: dict, node: dict, relevance: float,
                  selected_by: str = "llm", lex_coverage: Optional[float] = None,
                  lex_matched: Optional[int] = None) -> dict:
    """把选中节点转成 sources 兼容结果（设计 §4.2）。

    selected_by: "llm"（LLM 语义判定命中）/ "lexical_fallback"（LLM 判空后的词面降级命中）。
    注意：retrieve 内已持有 db；此函数通过全局 SessionLocal 查 chunk 锚点
    （独立短会话，避免跨会话访问 ORM 对象）。
    """
    from app.core.database import SessionLocal
    full_text = doc.full_text or ""
    start = int(node.get("start", 0))
    end = int(node.get("end", 0))
    metadata = {
        "node_id": node.get("node_id"),
        "node_title": node.get("title"),
        "char_start": start,
        "char_end": end,
        "truncated": False,
        "score_source": "llm_relevance" if selected_by == "llm" else "lexical_fallback",
        "selected_by": selected_by,
    }
    if lex_coverage is not None:
        metadata["lex_coverage"] = lex_coverage
        metadata["lex_matched"] = lex_matched
    # R8：越界节点丢弃标记
    if start < 0 or end > len(full_text) or end <= start:
        metadata["stale"] = True
        content = full_text[max(0, start):min(end, len(full_text))] or full_text[:MAX_CONTENT_CHARS]
    else:
        content = full_text[start:end]
        if tree.get("stale"):
            metadata["stale"] = True
    if len(content) > MAX_CONTENT_CHARS:
        content = content[:MAX_CONTENT_CHARS]
        metadata["truncated"] = True

    with SessionLocal() as db:
        chunk_id, chunk_index = _first_chunk_anchor(db, doc)

    return {
        "chunk_id": chunk_id,
        "document_id": str(doc.id),
        "filename": doc.filename,
        "chunk_index": chunk_index,
        "content": content,
        "score": round(relevance, 2),
        "match_type": "pageindex",
        "metadata": metadata,
    }
