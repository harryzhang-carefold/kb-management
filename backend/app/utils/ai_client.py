"""AI 客户端：Embedding + LLM（均为 OpenAI 兼容 API）。"""
from typing import Iterator, Optional
import time

from loguru import logger
from openai import OpenAI, APIConnectionError, APIStatusError

from app.core.config import settings


class EmbeddingClient:
    """远程 Embedding（OpenAI 兼容 /v1/embeddings）。"""

    def __init__(self):
        self._client: Optional[OpenAI] = None

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(
                base_url=settings.embedding_base_url,
                api_key=settings.embedding_api_key or "not-set",
                timeout=60,
                max_retries=0,
            )
        return self._client

    def embed(self, texts: list[str]) -> list[list[float]]:
        """批量生成向量。空文本列表返回 []。"""
        if not texts:
            return []
        # OpenAI 兼容接口通常单次最多 2048 条，这里按 256 分批
        results: list[list[float]] = []
        batch = 256
        for i in range(0, len(texts), batch):
            chunk = texts[i:i + batch]
            resp = self.client.embeddings.create(
                model=settings.embedding_model,
                input=chunk,
            )
            # 按 index 排序保证顺序
            resp.data.sort(key=lambda x: x.index)
            results.extend([d.embedding for d in resp.data])
        return results

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]

    def get_dim(self) -> int:
        """探测 embedding 维度（用于初始化索引）。"""
        v = self.embed_one("dim probe")
        return len(v)


class LLMClient:
    """远程 LLM（OpenAI 兼容 /v1/chat/completions），支持流式。"""

    def __init__(self):
        self._client: Optional[OpenAI] = None

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key or "not-set",
                timeout=120,
                max_retries=1,
            )
        return self._client

    def chat_stream(self, messages: list[dict], temperature: float = 0.2,
                    max_tokens: int = 2048) -> Iterator[dict]:
        """流式 chat。yield: {'type':'token','token':str} ... {'type':'done','full':str,'token_count':int}"""
        stream = self.client.chat.completions.create(
            model=settings.llm_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        full = ""
        token_count = 0
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                full += delta.content
                token_count += 1
                yield {"type": "token", "token": delta.content}
        yield {"type": "done", "full": full, "token_count": token_count}

    def health(self) -> bool:
        try:
            self.client.models.list()
            return True
        except Exception:
            return False


class EmbeddingHealth:
    @staticmethod
    def check() -> bool:
        try:
            c = EmbeddingClient()
            c.embed_one("health")
            return True
        except Exception as e:
            logger.warning(f"Embedding health check failed: {e}")
            return False


embedding_client = EmbeddingClient()
llm_client = LLMClient()
