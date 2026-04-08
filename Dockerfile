# 使用 Python 3.9 轻量级镜像
FROM python:3.9-slim

# 设置时区为北京时间，确保日志时间正确
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app

# 安装必要的系统工具 (curl 和 bash)，并安装 Koyeb CLI
RUN apt-get update && apt-get install -y curl bash && \
    curl -sSl https://raw.githubusercontent.com/koyeb/koyeb-cli/master/install.sh | bash && \
    mv /root/.koyeb/bin/koyeb /usr/local/bin/koyeb && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 验证 Koyeb CLI 是否安装成功
RUN koyeb version

# 复制 Python 脚本到容器
COPY koyeb_wake.py .

# 容器启动时运行 Python 脚本
CMD ["python", "koyeb_wake.py"]
