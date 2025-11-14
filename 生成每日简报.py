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

# --- 修改点 1：函数重命名并更新其内部逻辑 ---
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
                # --- 修改点 1.1：时间范围从 TheLastWeek 改为 TheLastDay ---
                "conditions": [{"field_name": "发布日期", "operator": "is", "value": ["Yesterday"]}] 
            },
            # --- 修改点 1.2：获取的字段改为 "完整信息内容" 和 "视频链接" ---
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
                # --- 修改点 1.3：获取新的字段内容 ---
                info_raw = fields.get('完整信息内容')
                link = fields.get('视频链接')
                
                if info_raw:
                    info_text = parse_rich_text(info_raw).strip()
                    # --- 修改点 1.4：保存包含内容和链接的字典 ---
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

# --- 修改点 2：更新生成报告的函数，以处理新的数据结构和Prompt ---
def generate_report_string(info_entries):
    """调用大模型，根据带有出处和链接的信息生成完整的日报内容字符串"""
    if not info_entries:
        print("没有信息数据，无法生成日报。")
        return None
        
    raw_text_data_with_links = []
    for item in info_entries:
        # 如果链接为空或不存在，则提供一个提示
        link = item.get('link') if item.get('link') else "无可用链接"
        entry_str = f"[来源链接: {link}]\n内容: {item.get('content', '')}"
        raw_text_data_with_links.append(entry_str)
    
    final_input_for_llm = "\n--------------------\n".join(raw_text_data_with_links)
    
    # --- 关键修改点：更新 Prompt，要求明确指出观点提出者 ---
    prompt_template = """
你是一名专业的行业分析师，专注于中国电竞场馆及线下娱乐行业。你的任务是分析一系列包含来源链接和发布者信息的原始视频内容片段，并从中提炼出尽可能丰富、具有价值的行业观点。要求不仅总结视频中明确表达的内容，也要根据语气、背景、场景、表达方式等，提炼出潜在趋势、行业启示和关键细节，形成专业的《电竞场馆 / 网咖行业近期观点日报》。

------------------------------------
【输出格式要求（必须遵守）】
------------------------------------
每条内容按如下结构输出：

一、发布者姓名认为：
* 观点提炼点 1  
* 观点提炼点 2  
* 观点提炼点 3  
（如有更多可继续补充）
[源](视频链接)

要求：
1. 发布者必须位于开头：“王某某认为：”
2. 全部观点使用 `*` 列表呈现。
3. 每条内容至少 **3 个以上要点**，尽可能丰富。
4. 每条观点最后必须包含 Markdown 形式链接 `[源](URL)`。
5. 所有内容按“一、二、三……”编号排序。
6. 输出必须为 **中文**，使用 **Markdown**。

------------------------------------
【内容提炼方式（更自然，不死板）】
------------------------------------
你需要对每个视频进行深度理解，从以下维度中自由提取，但不需要在输出中逐条说明来源：

- 视频中明确提到的核心观点  
- 与行业相关的补充分析（如需求、客群、场景、经营逻辑）  
- 语境中体现出的行业趋势或潜在信号  
- 视频提及的数据、实例、行为场景  
- 可推导的行业风险、机会或矛盾点  
- 对电竞场馆/网咖行业运营具有启发意义的观察  

**注意：不要在成品文字中出现提示性语句，例如“视频未明确但可从语境推断”“若存在风险”等。只需直接写出观点。**

最终呈现效果应像一个真实专业的行业日报，而非分析模板或教学文。

------------------------------------
【输入格式】
------------------------------------
原始视频内容片段如下，各片段以 "--------------------" 分隔，每片段开头都有：
[来源链接: ...]
后续包含视频发布者及观点信息。
变量：
{raw_text_data_with_links}

------------------------------------
【最终任务】
------------------------------------
请根据以上要求生成《电竞场馆/网咖行业近期观点日报》，严格按照“发布者 → 观点列表 → 视频链接”格式输出，每条观点内容尽可能丰富、自然、有洞察。
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

    post_url = CF_WORKER_URL
    
    print(f"\n正在将报告发送到 {post_url} ...")
    try:
        response = requests.post(post_url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        print(f"报告保存成功！服务器响应: {response.json()}")
    except requests.exceptions.RequestException as e:
        print(f"发送报告失败: {e}")
        if hasattr(e, 'response') and e.response:
            print(f"服务器响应 (状态码 {e.response.status_code}): {e.response.text}")

def main():
    """主执行函数"""
    print("--- 开始执行每日行业观点简报生成任务 ---")
    
    if not check_env_vars():
        return

    token = get_tenant_access_token(APP_ID, APP_SECRET)
    if not token:
        print("\n程序终止。")
        return

    # --- 修改点 3：调用更新后的函数 ---
    info_entries = get_daily_info_with_links(token)
    if not info_entries:
        print("\n未找到任何信息，程序终止。")
        return

    report_content = generate_report_string(info_entries)
    
    save_report_via_worker(report_content)
    
    print("\n--- 任务执行完毕 ---")


if __name__ == "__main__":
    main()
