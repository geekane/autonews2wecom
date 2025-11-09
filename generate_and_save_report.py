import os
import requests
from datetime import datetime
# ... (你的其他函数)

# 确保这个函数在你的脚本中
def save_report_via_worker(report_content):
    # 从 GitHub Actions Secrets 读取环境变量
    worker_url = os.environ.get("CF_WORKER_URL") 
    auth_secret = os.environ.get("CF_AUTH_SECRET")

    if not worker_url or not auth_secret:
        print("错误：缺少 CF_WORKER_URL 或 CF_AUTH_SECRET 环境变量。")
        return

    today_date = datetime.now().strftime('%Y-%m-%d')
    headers = {
        'Authorization': f'Bearer {auth_secret}',
        'Content-Type': 'application/json'
    }
    payload = {
        'date': today_date,
        'content': report_content
    }

    # Worker 的 POST 路径是根路径 '/'
    post_url = worker_url 
    
    print(f"\n正在将报告发送到 {post_url} ...")
    try:
        response = requests.post(post_url, headers=headers, json=payload)
        response.raise_for_status() # 如果状态码不是 2xx，则抛出异常
        print(f"报告保存成功！响应: {response.json()}")
    except requests.exceptions.RequestException as e:
        print(f"发送报告失败: {e}")
        if e.response:
            print(f"服务器响应: {e.response.text}")

# ... (你的 main 和 generate_report_string 函数)
