FROM python:3.9-slim

# 2. 设置工作目录
WORKDIR /app

# 3. 复制项目文件
COPY . .

# 4. 安装依赖 (如果你的动作有 requirements.txt)
# RUN pip install --no-cache-dir -r requirements.txt

# 5. 定义容器启动命令 (假设你的逻辑在 main.py)
CMD ["python", "main.py"]
