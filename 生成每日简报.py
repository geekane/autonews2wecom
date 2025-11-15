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
你是一名专业的行业分析师，专注于中国电竞场馆及线下娱乐行业。你的任务是基于原始视频内容片段，提取并扩写成信息丰富、逻辑清晰、具深度洞察的行业观点。要求每条视频的观点内容必须“更长、更细、更全面”，像真实行业专家撰写的深度日报，而不是简短总结。

------------------------------------
【输出格式要求】
------------------------------------
每条内容严格按以下结构呈现：

一、发布者姓名认为：
* 观点 1（进行充分扩写，而不是只写一句话）
* 观点 2（对背景、场景、逻辑进行补充说明）
* 观点 3（延展行业含义或经营启示）
* 如视频信息丰富，可继续写更多观点
[源](视频链接)

要求：
1. 开头必须是：“某某某（根据实际情况调整账号名）认为：”
2. * 列表必须至少 **4–6 条观点**，并且每条观点都要写成 **完整表达句**，不能太短。
3. 所有内容按 “一、二、三……” 排序。
4. 观点务必自然流畅，不要写分析模板词，如“视频未明确但……”“若存在风险……”“补充观点/背景判断”等。
5. 写作风格要像详细汇总的日报。

------------------------------------
【内容扩写要求（重点）】
------------------------------------
每条视频的内容需写得更丰满，做到：

- 详细拆解发布者原意，而不是简单复述  
- 对其观点背后的经营逻辑、用户心理、场景细节做进一步说明  
- 若视频内容包含动作、语气、情绪、店内场景等，也要提取并写进文字  
- 补充该观点对电竞场馆/网咖经营的启示或行业相关性  
- 语言自然，不写模板化词语  

你可以（但不强制）将一个简单观点扩写为：
- 背景 → 现象 → 逻辑 → 启示 的内容结构  
- 或“观点＋原因＋举例＋行业意义”的形式  

但不要显式写出结构说明，只要写出流畅自然的内容即可。

------------------------------------
【输入格式】
------------------------------------
原始视频内容片段如下，以 "--------------------" 分隔，每段含：
[来源链接: ...]
以及视频发布者与内容描述。
变量：
{raw_text_data_with_links}

------------------------------------
【最终任务】
------------------------------------
请根据以上要求生成《电竞场馆/网咖行业近期观点日报》，让每条视频的观点更详细、更深入、更有信息量、阅读感更强。
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
