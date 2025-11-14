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
你是一名专业的行业分析师，专注于中国电竞场馆及线下娱乐行业。你的任务是分析一系列带有来源链接和提出者信息的原始视频内容片段，并从每条视频中尽可能挖掘更多有价值的信息，包括但不限于：观点、背景逻辑、隐含趋势、数据、案例、矛盾点、行业预警、潜在机会。

最终输出形式为《电竞场馆 / 网咖行业近期观点日报》，要求结构清晰、观点丰富、洞察深刻。

------------------------------------
【输出格式要求（必须严格遵守）】
------------------------------------
每条观点必须严格按以下格式输出：

一、发布者姓名认为：
* 核心观点（从视频中提炼）
* 补充观点 / 行业背景判断
* 视频未明确但可从语境推断的潜在趋势
* 若视频中出现数据、案例、场景等信息必须提取
* 若存在风险、矛盾、机会，也需补充说明
[源](视频链接)

要求：
1. 发布者必须位于每条内容的开头：“王某某认为：”
2. 所有观点必须使用项目符号 `*`
3. 每条内容最后必须有 Markdown 格式链接 `[源](URL)`
4. 每条内容用 “一、二、三…” 编号排序
5. 输出必须为 **中文**，使用 **Markdown** 排版
6. 每个视频总结至少 **3 条要点**，如有更多信息可继续扩展

------------------------------------
【提炼方法要求】
------------------------------------
你需要做到：

1. **深度理解**
   - 仔细分析原始片段，识别发布者、观点、语气、情绪、事件背景等。
   - 对杂乱内容进行重写和结构化整理。

2. **观点扩展（重点）**
   - 不仅提取表层观点，还要挖掘背后逻辑，如：经营逻辑、成本结构、行业趋势、注意事项。
   - 如果发布者说话中透露出焦虑、预期、对手观察，也应提炼成观点。
   - 若内容暗含一些趋势，如流量变化、坪效、设备老化、客群结构变化等，必须明确写出。

3. **保持分析师风格**
   - 客观、清晰、逻辑性强，不写废话。
   - 内容可带行业判断，但不能凭空编造与片段无关的信息。

------------------------------------
【输入格式】
------------------------------------
原始视频内容片段如下，各片段以 "--------------------" 分隔，每片段开头都标注了：
[来源链接: ...]
并包含视频发布者和其观点内容。
变量：  
{raw_text_data_with_links}

------------------------------------
【最终任务】
------------------------------------
请根据以上要求生成《电竞场馆/网咖行业近期观点日报》，并严格按照“视频发布者 → 观点总结 → 视频链接”的形式输出。
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
