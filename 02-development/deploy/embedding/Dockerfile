# 本地 OpenAI 兼容 Embedding 服务（sentence-transformers，CPU）
# 替代不可达的外部端点 34.64.61.208:4000 (gte-qwen2)
# 模型：paraphrase-multilingual-MiniLM-L12-v2（多语言含中文，384 维，~118M 参数，CPU 友好）
FROM python:3.11-slim

WORKDIR /app

# 依赖（CPU 版 torch，避免拉 CUDA 大包）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu torch

# 应用
COPY app.py .

# 预拉取模型到镜像，避免首启动下载（HF 可达）
RUN python -c "from sentence_transformers import SentenceTransformer; \
    m=SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2'); \
    m.encode(['warmup']); print('model baked:', len(m.encode(['x'])[0]))"

ENV EMBED_MODEL=paraphrase-multilingual-MiniLM-L12-v2 \
    EMBED_DEVICE=cpu \
    EMBED_MAX_BATCH=64 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    PORT=8100

EXPOSE 8100
CMD ["sh", "-c", "exec uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
