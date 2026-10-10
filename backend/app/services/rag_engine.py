"""RAG 引擎：混合检索 + Prompt 构建 + LLM 流式生成。"""
from typing import Iterator, Optional
import json
import re

from loguru import logger

from app.core.config import settings
from app.utils.es_client import es_client
from app.utils.ai_client import embedding_client, llm_client


SYSTEM_PROMPT_DEFAULT = (
    "你是一个专业的知识库助手。请严格基于【参考片段】回答用户问题。\n"
    "规则：\n"
    "1. 只依据参考片段中的信息作答，不要编造。\n"
    "2. 如果参考片段没有相关信息，明确说明「知识库中未找到相关内容」。\n"
    "3. 在引用具体片段时，用 [1] [2] 等标注来源编号。\n"
    "4. 回答简洁、条理清晰，使用 Markdown 格式。\n"
)


def _build_prompt(system_prompt: Optional[str], question: str,
                  sources: list[dict]) -> list[dict]:
    """构建 LLM messages。sources: [{chunk_id, content, filename, chunk_index, score}]"""
    sys_prompt = system_prompt or SYSTEM_PROMPT_DEFAULT
    refs = []
    for i, s in enumerate(sources, start=1):
        refs.append(f"[{i}] (来源: {s.get('filename','')}, 第{s.get('chunk_index',0)}段)\n{s.get('content','')}")
    context = "\n\n---\n\n".join(refs) if refs else "（无参考片段）"

    user_prompt = (
        f"【参考片段】\n{context}\n\n"
        f"【用户问题】\n{question}"
    )
    return [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_prompt},
    ]


class RAGEngine:
    def stream_answer(self, kb_id: str, question: str,
                      history: list[dict], top_n: int = 5,
                      system_prompt: Optional[str] = None) -> Iterator[dict]:
        """
        RAG 流式问答。
        yield:
          {"type":"meta","sources":[...]}
          {"type":"token","token":str}
          {"type":"done","full":str,"token_count":int}
        """
        # 1. question embedding
        try:
            qvec = embedding_client.embed_one(question)
        except Exception as e:
            logger.error(f"Embedding failed: {e}")
            yield {"type": "error", "message": f"Embedding 服务不可用: {e}"}
            return

        # 2. 混合检索
        try:
            hits, took_ms = es_client.hybrid_search(
                kb_id=kb_id, query=question, query_vector=qvec,
                mode="hybrid", top_k=settings.rag_top_k,
            )
        except Exception as e:
            logger.error(f"ES search failed: {e}")
            yield {"type": "error", "message": f"检索服务不可用: {e}"}
            return

        sources = hits[:top_n]

        # 3. 构建 sources 元数据
        source_meta = [{
            "chunk_id": s["chunk_id"],
            "document_id": s["document_id"],
            "filename": s["filename"],
            "chunk_index": s["chunk_index"],
            "score": s.get("score", 0.0),
        } for s in sources]

        yield {"type": "meta", "sources": source_meta, "took_ms": took_ms}

        # 4. 构建 messages（含历史）
        messages = _build_prompt(system_prompt, question, sources)
        # 附加历史（最近的几轮）
        if history:
            recent = history[-6:]
            for h in recent:
                messages.insert(1, {"role": h["role"], "content": h["content"]})

        # 5. LLM 流式生成
        full = ""
        try:
            for event in llm_client.chat_stream(messages):
                if event["type"] == "token":
                    full += event["token"]
                    yield {"type": "token", "token": event["token"]}
                elif event["type"] == "done":
                    yield {"type": "done", "full": full,
                           "token_count": event["token_count"],
                           "sources": source_meta}
        except Exception as e:
            logger.error(f"LLM stream failed: {e}")
            yield {"type": "error", "message": f"LLM 服务异常: {e}"}


rag_engine = RAGEngine()
