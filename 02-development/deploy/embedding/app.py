"""本地 OpenAI 兼容 Embedding 服务（sentence-transformers，CPU）。

替代已不可达的外部端点 34.64.61.208:4000（gte-qwen2）。
端点：POST /v1/embeddings {model, input: [..] | "str"}  → OpenAI 格式
      GET  /v1/models
      GET  /health

说明：
- 向量维度由模型决定（paraphrase-multilingual-MiniLM-L12-v2 = 384）。
  与旧 gte-qwen2 (3584) 不同；当前 ES 索引与 chunk 表均为空，
  切换维度无存量数据兼容问题（见 BUGFIX_REPORT）。
- 不做归一化：ES dense_vector similarity=cosine 自带归一化。
"""
import os
import time

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

MODEL_NAME = os.environ.get("EMBED_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")
MAX_BATCH = int(os.environ.get("EMBED_MAX_BATCH", "64"))

app = FastAPI(title="local-embedding")

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        import torch
        from sentence_transformers import SentenceTransformer

        _engine = SentenceTransformer(
            MODEL_NAME,
            device=os.environ.get("EMBED_DEVICE", "cpu"),
            model_kwargs={"trust_remote_code": True},
        )
        # warmup
        _engine.encode(["warmup"], batch_size=1, show_progress_bar=False)
        _torch = torch
    return _engine


class EmbedRequest(BaseModel):
    model: str
    input: list | str
    encoding_format: str = "float"


@app.get("/health")
def health():
    dim = 0
    try:
        v = get_engine().encode(["dim"], batch_size=1)
        dim = len(v[0])
    except Exception as e:  # pragma: no cover
        return {"status": "error", "error": str(e)[:200]}
    return {"status": "ok", "model": MODEL_NAME, "dim": dim}


@app.get("/v1/models")
def models():
    return {"object": "list", "data": [
        {"id": MODEL_NAME, "object": "model", "owned_by": "local", "root": MODEL_NAME},
    ]}


@app.post("/v1/embeddings")
def embeddings(req: EmbedRequest):
    texts = [req.input] if isinstance(req.input, str) else list(req.input)
    if not texts:
        return {"object": "list", "data": [], "model": req.model, "usage": {"prompt_tokens": 0, "total_tokens": 0}}
    engine = get_engine()
    vectors = []
    t0 = time.time()
    for i in range(0, len(texts), MAX_BATCH):
        sub = texts[i:i + MAX_BATCH]
        vectors.extend(engine.encode(sub, batch_size=MAX_BATCH, show_progress_bar=False).tolist())
    data = [
        {"object": "embedding", "index": i, "embedding": v}
        for i, v in enumerate(vectors)
    ]
    return {
        "object": "list",
        "data": data,
        "model": req.model,
        "usage": {"prompt_tokens": 0, "total_tokens": len(texts), "elapsed_ms": int((time.time() - t0) * 1000)},
    }
