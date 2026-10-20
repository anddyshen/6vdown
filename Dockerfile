# 6vdown / C2Down - 轻量 Docker 容器镜像
FROM python:3.12-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量：输出无缓冲，指定数据持久化目录
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai \
    C2DOWN_DATA_DIR=/app/data

# 预先安装服务端轻量依赖（利用缓存加速构建）
COPY requirements-server.txt /app/
RUN pip install --no-cache-dir -r requirements-server.txt

# 复制项目代码与资源（排除项见 .dockerignore）
COPY src/ /app/src/
COPY server.py /app/server.py

# 声明挂载卷与端口
VOLUME ["/app/data"]
EXPOSE 8080

# 默认启动命令
ENTRYPOINT ["python", "server.py", "--host", "0.0.0.0", "--port", "8080"]

