import os
import requests
import json
from datetime import datetime
from openai import OpenAI

# --- 1. 从环境变量加载配置信息 ---
# 这种方式更安全，尤其是在CI/CD环境中（如GitHub Actions）
# 飞书 API 配置
APP_ID = os.environ.get("FEISHU_APP_ID")
APP_SECRET = os.environ.get("FEISHU_APP_SECRET")
APP_TOKEN = "BJ2gbK1onahpjZsglTgcxo7Onif" # 这个通常是固定的，可以硬编码
TABLE_ID = "tbliEUHB9iSxZuiY" # 这个通常是固定的，可以硬编码

# ModelScope LLM API 配置
MODELSCOPE_API_KEY = os.environ.get("MODELSCOPE_API_KEY")
MODELSCOPE_MODEL_ID = "Qwen/Qwen3-Next-80B-A3B-Thinking" # 推荐使用增强版以获得更好的长文本总结能力
MODELSCOPE_BASE_URL = "https://api-inference.modelscope.cn/v1"

# Cloudflare Worker 配置
CF_WORKER_URL = os.environ.get("CF_WORKER_URL")
CF_AUTH_SECRET = os.environ.get("CF_AUTH_SECRET")

# --- 2. API 端点 ---
TENANT_ACCESS_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal/"
SEARCH_RECORDS_URL = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records/search"


def check_env_vars():
    """检查所有必要的环境变量是否已设置"""
    required_vars = [
        "FEISHU_APP_ID", "FEISHU_APP_SECRET",
        "MODELSCOPE_API_KEY", "CF_WORKER_URL", "CF_AUTH_SECRET"
    ]
    missing_vars = [var for var in required_vars if not os.environ.get(var)]
    if missing_vars:
        print(f"错误：以下环境变量未设置: {', '.join(missing_vars)}")
        return False
    return True

def get_tenant_access_token(app_id, app_secret):
    """获取 tenant_access_token"""
    payload = {"app_id": app_id, "app_secret": app_secret}
    headers = {'Content-Type': 'application/json'}
    print("正在获取飞书 access_token...")
    try:
        response = requests.post(TENANT_ACCESS_TOKEN_URL, json=payload, headers=headers)
        response.raise_for_status()
        result = response.json()
        if result.get("code") == 0:
            print("获取 access_token 成功！")
            return result.get("tenant_access_token")
        else:
            print(f"获取 access_token 失败: {result.get('msg')}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"网络请求失败: {e}")
        return None

def parse_rich_text(field_value):
    """解析飞书多维表格的“多行文本”字段"""
    if not isinstance(field_value, list):
        return str(field_value)
    text_parts = []
    for item in field_value:
        if item.get("type") == "text":
            text_parts.append(item.get("text", ""))
    return "".join(text_parts)

def get_recent_video_scripts(access_token):
    """获取多维表格中最近7天内发布的视频文案"""
    headers = {'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'}
    video_scripts_data = []
    page_token = ""
    print("\n开始查询最近7天的视频文案...")
    while True:
        payload = {
            "filter": {"conjunction": "and", "conditions": [{"field_name": "发布日期", "operator": "is", "value": ["TheLastWeek"]}]},
            "field_names": ["视频文案", "发布日期"],
            "page_size": 100,
            "page_token": page_token
        }
        try:
            response = requests.post(SEARCH_RECORDS_URL, json=payload, headers=headers)
            response.raise_for_status()
            result = response.json()
            if result.get("code") != 0:
                print(f"查询记录失败: {result.get('msg')}")
                break
            data = result.get("data", {})
            items = data.get("items", [])
            if not items and not page_token:
                break
            for item in items:
                fields = item.get('fields', {})
                script_raw = fields.get('视频文案')
                if script_raw:
                    script_text = parse_rich_text(script_raw).strip()
                    video_scripts_data.append({"text": script_text})
            if data.get('has_more'):
                page_token = data.get('page_token')
            else:
                break
        except requests.exceptions.RequestException as e:
            print(f"查询记录时网络请求失败: {e}")
            break
    print(f"查询完成，共找到 {len(video_scripts_data)} 条文案。")
    return video_scripts_data

def generate_report_string(scripts):
    """调用大模型，根据文案生成完整的日报内容字符串"""
    if not scripts:
        print("没有文案数据，无法生成日报。")
        return None
        
    all_texts = [item['text'] for item in scripts]
    raw_text_data_for_llm = "\n--------------------\n".join(all_texts)
    
    prompt_template = """
你是一名专业的行业分析师，专注于中国的电竞场馆及线下娱乐行业。你的任务是分析一系列来自行业内部的原始文本片段（视频文案），并从中提炼、总结出核心观点，最终以一份结构清晰、洞察深刻的“观点日报”形式呈现。

**任务要求:**
1. **深入理解**: 仔细阅读并理解下面提供的所有原始文本片段。
2. **提炼主题**: 从文本中识别出几个关键的、反复出现的核心议题。例如：行业趋势、运营管理、市场营销、创新模式、人才观念等。
3. **构建报告结构**: 严格按照以下结构生成报告：
    * **报告摘要**: 在报告开头，用一段话高度概括所有文本的核心思想和行业的主要变化趋势。
    * **分点论述**: 根据你提炼出的核心议题，创建几个大的板块（例如：“一、核心趋势：从‘硬件为王’到‘体验制胜’”）。
    * **要点总结**: 在每个大的板块下，使用项目符号（bullet points）的形式，清晰、简洁地总结出具体的观点和案例。要求是综合提炼，而不是直接摘抄原文。
4. **专业口吻**: 全程使用专业、客观、具有前瞻性的分析师口吻。
5. **语言**: 报告全文使用中文，并使用 Markdown 格式化，例如使用 `##` 作为大标题，使用 `*` 作为列表项。

**原始文本片段如下，各片段以 "--------------------" 分隔:**
{raw_text_data}

请根据以上要求，开始撰写你的“电竞场馆/网咖行业近期观点日报”。
"""
    final_prompt = prompt_template.format(raw_text_data=raw_text_data_for_llm)

    print("\n正在请求 ModelScope 生成观点日报...")
    try:
        client = OpenAI(base_url=MODELSCOPE_BASE_URL, api_key=MODELSCOPE_API_KEY)
        response = client.chat.completions.create(
            model=MODELSCOPE_MODEL_ID,
            messages=[{'role': 'user', 'content': final_prompt}],
            stream=False # 设置为 False 以获取完整响应
        )
        report_content = response.choices[0].message.content
        print("日报内容生成成功！")
        return report_content
    except Exception as e:
        print(f"调用大模型时发生错误: {e}")
        return None

def save_report_via_worker(report_content):
    """将生成的报告通过HTTP POST发送到Cloudflare Worker"""
    if not report_content:
        print("报告内容为空，跳过保存步骤。")
        return
        
    today_date = datetime.now().strftime('%Y-%m-%d')
    headers = {
        'Authorization': f'Bearer {CF_AUTH_SECRET}',
        'Content-Type': 'application/json'
    }
    payload = {
        'date': today_date,
        'content': report_content
    }

    # Worker 的 POST 路径是根路径 '/'
    post_url = CF_WORKER_URL
    
    print(f"\n正在将报告发送到 {post_url} ...")
    try:
        response = requests.post(post_url, headers=headers, json=payload, timeout=30)
        response.raise_for_status() # 如果状态码不是 2xx，则抛出异常
        print(f"报告保存成功！服务器响应: {response.json()}")
    except requests.exceptions.RequestException as e:
        print(f"发送报告失败: {e}")
        if e.response:
            print(f"服务器响应 (状态码 {e.response.status_code}): {e.response.text}")

def main():
    """主执行函数"""
    print("--- 开始执行每日行业观点简报生成任务 ---")
    
    # 0. 检查环境变量
    if not check_env_vars():
        return # 如果环境变量缺失，则终止程序

    # 1. 获取飞书 token
    token = get_tenant_access_token(APP_ID, APP_SECRET)
    if not token:
        print("\n程序终止。")
        return

    # 2. 获取文案数据
    scripts = get_recent_video_scripts(token)
    if not scripts:
        print("\n未找到任何文案，程序终止。")
        return

    # 3. 调用大模型生成日报
    report_content = generate_report_string(scripts)
    
    # 4. 将日报内容保存到 D1
    save_report_via_worker(report_content)
    
    print("\n--- 任务执行完毕 ---")


if __name__ == "__main__":
    main()
