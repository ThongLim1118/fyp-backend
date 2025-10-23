FROM python:3.11-slim
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
ENV PYTHONPATH=/app/src

COPY user_data /user_data


CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "/app/src"]



# FROM python:3.11-slim

# # 在容器内建立主工作目录
# WORKDIR /app

# # === 安装主应用依赖 ===
# COPY requirements.txt ./
# RUN pip install --no-cache-dir -r requirements.txt

# # === 安装 user_data 插件包（方案A）===
# COPY user_data /plugins
# RUN pip install --no-cache-dir -e /plugins

# # === 拷贝主应用代码 ===
# COPY src ./src

# # === 设置 Python 搜索路径 ===
# ENV PYTHONPATH=/app/src

# # === 启动命令（可按实际调整） ===
# CMD ["python", "-m", "app.main.cli", "--help"]
