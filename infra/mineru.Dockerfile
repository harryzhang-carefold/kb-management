# MinerU 文档解析服务 — 纯 CPU 部署（kb-management 配套）
# 官方镜像默认面向 GPU，此处用 python:3.10-slim 自建 CPU 镜像
# 模型首次启动自动下载（~2GB），缓存到 kb_mineru_models 卷
FROM python:3.10-slim

# 字体（OCR/渲染需要）+ 依赖库
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-noto-core fonts-noto-cjk fontconfig libgl1 \
    libglib2.0-0 libsm6 libxext6 libxrender1 \
    && fc-cache -fv \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# MinerU 核心（无 CUDA 依赖）+ VLM 工具链
RUN pip install --no-cache-dir -U 'mineru[core]'

# 模型来源：modelscope（国内直连，首次启动自动下载到默认缓存目录）
ENV MINERU_MODEL_SOURCE=modelscope
ENV HOME=/root
RUN pip cache purge

EXPOSE 8000

# MinerU 4.x 分层 API：
#   flash  = 轻量解析（Office/HTML/CSV，无需模型）
#   basic/standard/advanced = VLM 解析（PDF/图片，CPU 可运行，模型首次自动下载）
# --preload-models 让模型在服务启动时就绪（首次会触发下载）
ENTRYPOINT ["mineru-api", "--host", "0.0.0.0", "--port", "8000", "--tier", "basic", "--preload-models", "--concurrency", "2"]
