# ==============================================================================
# OmniRSS Ultra-Lightweight Production Dockerfile
# Base: Python 3.12-slim (Debian based, < 150MB RAM footprint)
# ==============================================================================
FROM python:3.12-slim AS builder

WORKDIR /app

# 安裝基礎編譯工具 (為 nh3, argon2-cffi, aiosqlite 等 C 擴展構建 wheel)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt


# ==============================================================================
# 運行階段 (Runner)
# ==============================================================================
FROM python:3.12-slim AS runner

WORKDIR /app

# 安裝運行時必需的輕量套件 (sqlite3, zstd, ca-certificates)
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    zstd \
    ca-certificates \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# 從 builder 複製已安裝的 python 套件
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# 建立預設工作目錄
RUN mkdir -p /app/data /app/plugins /app/layouts /app/locales /app/logs

# 複製專案代碼
COPY omnirss /app/omnirss
COPY layouts /app/layouts
COPY locales /app/locales

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "omnirss.main:app", "--host", "0.0.0.0", "--port", "8000"]
