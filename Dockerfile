# c:\Users\yuanting\Desktop\project_stock\Dockerfile
FROM python:3.12-slim

# 設定工作目錄
WORKDIR /app

# 安裝系統依賴 (如果你確定某些 Python 套件需要 build-essential 則保留)
# 移除了 proxy, curl wget 等 Cloud Run 不需要用到的工具
RUN apt-get update && apt-get install -y \
    build-essential netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# 複製與安裝 Python 套件
# 加上 --no-cache-dir 可以減少映像檔體積
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 複製所有程式碼到 container
COPY . /app

# 提示: 如果有 .dockerignore 檔案, 記得把 __pycache__ 和虛擬環境加進去

# 執行您的 Backend API
# 改用 gunicorn 作為正式環境的 WSGI Server
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 visualization_api_server_v2:app