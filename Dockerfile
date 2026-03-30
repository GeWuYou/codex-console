FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    WEBUI_HOST=0.0.0.0 \
    WEBUI_PORT=1455 \
    LOG_LEVEL=info \
    DEBUG=0

# ✅ 安装 Playwright 运行所需最小系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 \
    libatk-bridge2.0-0 \
    libx11-6 \
    libxcomposite1 \
    libxrandr2 \
    libgbm1 \
    libgtk-3-0 \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ✅ 安装 Python 依赖（包含 playwright）
COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    # 👇 只需要这一句，不要重复 pip install playwright
    && python -m playwright install chromium \
    && rm -rf /root/.cache

# 复制代码
COPY . .

EXPOSE 1455

CMD ["python", "webui.py"]