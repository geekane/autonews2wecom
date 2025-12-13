import os
import requests
import json
from datetime import datetime
from openai import OpenAI

# --- 1. 从环境变量加载配置信息 ---
# 飞书 API 配置
APP_ID = os.environ.get("FEISHU_APP_ID")
APP_SECRET = os.environ.get("FEISHU_APP_SECRET")
# 下面两个通常固定，如果需要变动也可改为环境变量
APP_TOKEN = "BJ2gbK1onahpjZsglTgcxo7Onif" 
TABLE_ID = "tbliEUHB9iSxZuiY" 

# ModelScope LLM API 配置
MODELSCOPE_API_KEY = os.environ.get("MODELSCOPE_API_KEY")
MODELSCOPE_MODEL_ID = "Qwen/Qwen3-Next-80B-A3B-Thinking" 
MODELSCOPE_BASE_URL = "https://api-inference.modelscope.cn/v1"

# Cloudflare Worker 配置
CF_WORKER_URL = os.environ.get("CF_WORKER_URL")

# 【关键修改】这里设置默认值为 '1234'，对应你 Cloudflare 后台的 AUTH_SECRET
# 如果你的系统环境变量里没有设置 CF_AUTH_SECRET，它就会自动使用 '1234'
CF_AUTH_SECRET = os.environ.get("CF_AUTH_SECRET", "1234")

# --- 2. API 端点 ---
TENANT_ACCESS_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal/"
SEARCH_RECORDS_URL = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records/search"


def check_env_vars():
    """检查必要的环境变量"""
    # CF_AUTH_SECRET 已经有了默认值，所以这里主要检查其他项
    required_vars = [
        "FEISHU_APP_ID", "FEISHU_APP_SECRET",
        "MODELSCOPE_API_KEY", "CF_WORKER_URL"
    ]
    missing_vars = [var for var in required_vars if not os.environ.get(var)]
    if missing_vars:
        print(f"错误：以下环境变量未设置: {', '.join(missing_vars)}")
        return False
    return True

def get_tenant_access_token(app_id, app_secret):
    """获取飞书 tenant_access_token"""
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

def get_daily_info_with_links(access_token):
    """获取多维表格中最近1天内发布的“完整信息内容”和“视频链接”"""
    headers = {'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'}
    info_data = []
    page_token = ""
    print("\n开始查询最近1天的信息内容...")
    while True:
        payload = {
            "filter": {
                "conjunction": "and", 
                "conditions": [{"field_name": "发布日期", "operator": "is", "value": ["Yesterday"]}] 
            },
            "field_names": ["完整信息内容", "视频链接", "发布日期"],
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
                info_raw = fields.get('完整信息内容')
                link = fields.get('视频链接')
                
                if info_raw:
                    info_text = parse_rich_text(info_raw).strip()
                    info_data.append({"content": info_text, "link": link})

            if data.get('has_more'):
                page_token = data.get('page_token')
            else:
                break
        except requests.exceptions.RequestException as e:
            print(f"查询记录时网络请求失败: {e}")
            break
    print(f"查询完成，共找到 {len(info_data)} 条信息。")
    return info_data

def generate_report_string(info_entries):
    """调用大模型生成日报"""
    if not info_entries:
        print("没有信息数据，无法生成日报。")
        return None
        
    raw_text_data_with_links = []
    for item in info_entries:
        link = item.get('link') if item.get('link') else "无可用链接"
        entry_str = f"[来源链接: {link}]\n内容: {item.get('content', '')}"
        raw_text_data_with_links.append(entry_str)
    
    final_input_for_llm = "\n--------------------\n".join(raw_text_data_with_links)
    
    prompt_template = """
你是一名专业的行业分析师，专注于中国电竞场馆及线下娱乐行业。你的任务是基于原始视频内容片段，提取并扩写成信息丰富、逻辑清晰、具深度洞察的行业观点。

------------------------------------
【输出格式要求】
------------------------------------
每条内容严格按以下结构呈现：

一、发布者姓名认为：
* 观点 1（进行充分扩写）
* 观点 2（补充背景或逻辑）
* 观点 3（延展行业含义）
...
[源](视频链接)

要求：
1. 开头必须是：“某某某（根据实际情况调整账号名）认为：”
2. * 列表必须至少 **4–6 条观点**，观点要写成 **完整表达句**。
3. 所有内容按 “一、二、三……” 排序。
4. 写作风格要像详细汇总的日报，避免模板化词语。

------------------------------------
【输入格式】
------------------------------------
{raw_text_data_with_links}

------------------------------------
【最终任务】
------------------------------------
请生成《电竞场馆/网咖行业近期观点日报》。
"""
    final_prompt = prompt_template.format(raw_text_data_with_links=final_input_for_llm)

    print("\n正在请求 ModelScope 生成观点日报...")
    try:
        client = OpenAI(base_url=MODELSCOPE_BASE_URL, api_key=MODELSCOPE_API_KEY)
        response = client.chat.completions.create(
            model=MODELSCOPE_MODEL_ID,
            messages=[{'role': 'user', 'content': final_prompt}],
            stream=False 
        )
        report_content = response.choices[0].message.content
        print("日报内容生成成功！")
        return report_content
    except Exception as e:
        print(f"调用大模型时发生错误: {e}")
        return None

def save_report_via_worker(report_content):
    """【关键修改】使用 X-Auth-Pass 发送报告到 Cloudflare Worker"""
    if not report_content:
        print("报告内容为空，跳过保存步骤。")
        return
        
    today_date = datetime.now().strftime('%Y-%m-%d')
    
    # --- 核心修改部分 ---
    # 使用 X-Auth-Pass，不再使用 Authorization: Bearer ...
    # 这与 Worker 端的修改相对应
    headers = {
        'X-Auth-Pass': CF_AUTH_SECRET, 
        'Content-Type': 'application/json'
    }
    # ------------------

    post_url = CF_WORKER_URL
    
    payload = {
        'date': today_date,
        'content': report_content
    }

    print(f"\n正在将报告发送到 {post_url} ...")
    try:
        response = requests.post(post_url, headers=headers, json=payload, timeout=30)
        
        # 检查响应
        if response.status_code == 200:
            print(f"报告保存成功！服务器响应: {response.json()}")
        else:
            print(f"保存失败 (状态码 {response.status_code})")
            print(f"服务器返回信息: {response.text}")
            
    except requests.exceptions.RequestException as e:
        print(f"发送报告网络请求错误: {e}")

def main():
    """主执行函数"""
    print("--- 开始执行每日行业观点简报生成任务 ---")
    
    if not check_env_vars():
        return

    token = get_tenant_access_token(APP_ID, APP_SECRET)
    if not token:
        print("\n程序终止。")
        return

    info_entries = get_daily_info_with_links(token)
    if not info_entries:
        print("\n未找到任何信息，程序终止。")
        return

    report_content = generate_report_string(info_entries)
    
    save_report_via_worker(report_content)
    
    print("\n--- 任务执行完毕 ---")


if __name__ == "__main__":
    main()
