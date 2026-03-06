import os
import requests
import json
from datetime import datetime
from openai import OpenAI

# ==========================================
# 1. 环境变量与配置信息加载
# ==========================================
APP_ID = os.environ.get("FEISHU_APP_ID")
APP_SECRET = os.environ.get("FEISHU_APP_SECRET")
APP_TOKEN = "BJ2gbK1onahpjZsglTgcxo7Onif" 
TABLE_ID = "tbliEUHB9iSxZuiY" 

CF_WORKER_URL = os.environ.get("CF_WORKER_URL")
CF_AUTH_SECRET = os.environ.get("CF_AUTH_SECRET", "1234")

TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")

# ==========================================
# 使用自定义的 Gemini LLM 配置
# ==========================================
CUSTOM_LLM_API_KEY = "123456" 
CUSTOM_LLM_MODEL_ID = "gemini-2.5-flash-lite" 
CUSTOM_LLM_BASE_URL = "https://aiclient-2-api-89ny.onrender.com/v1"

# ==========================================
# 2. API 端点定义
# ==========================================
TENANT_ACCESS_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal/"
SEARCH_RECORDS_URL = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records/search"

# ==========================================
# 3. 核心功能函数
# ==========================================
def check_env_vars():
    required_vars =[
        "FEISHU_APP_ID", "FEISHU_APP_SECRET",
        "CF_WORKER_URL", "TAVILY_API_KEY"
    ]
    missing_vars =[var for var in required_vars if not os.environ.get(var)]
    if missing_vars:
        print(f"错误：以下环境变量未设置: {', '.join(missing_vars)}")
        return False
    return True

def get_tenant_access_token(app_id, app_secret):
    payload = {"app_id": app_id, "app_secret": app_secret}
    headers = {'Content-Type': 'application/json'}
    print("正在获取飞书 access_token...")
    try:
        response = requests.post(TENANT_ACCESS_TOKEN_URL, json=payload, headers=headers)
        response.raise_for_status()
        result = response.json()
        if result.get("code") == 0:
            return result.get("tenant_access_token")
        else:
            print(f"获取 access_token 失败: {result.get('msg')}")
            return None
    except Exception as e:
        print(f"网络请求失败: {e}")
        return None

def parse_rich_text(field_value):
    if not isinstance(field_value, list):
        return str(field_value)
    text_parts =[]
    for item in field_value:
        if item.get("type") == "text":
            text_parts.append(item.get("text", ""))
    return "".join(text_parts)

def get_daily_info_with_links(access_token):
    headers = {'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'}
    info_data =[]
    page_token = ""
    print("\n开始查询飞书最近1天的内部信息内容...")
    while True:
        payload = {
            "filter": {
                "conjunction": "and", 
                "conditions":[{"field_name": "发布日期", "operator": "is", "value": ["Yesterday"]}] 
            },
            "field_names":["完整信息内容", "视频链接", "发布日期"],
            "page_size": 100,
            "page_token": page_token
        }
        try:
            response = requests.post(SEARCH_RECORDS_URL, json=payload, headers=headers)
            response.raise_for_status()
            result = response.json()
            if result.get("code") != 0:
                break
            data = result.get("data", {})
            items = data.get("items",[])
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
        except Exception as e:
            print(f"查询记录时网络请求失败: {e}")
            break
    print(f"飞书查询完成，共找到 {len(info_data)} 条内部观点。")
    return info_data

def get_industry_news():
    print("\n开始通过 Tavily 获取外部行业最新资讯...")
    url = "https://api.tavily.com/search"
    payload = {
        "api_key": TAVILY_API_KEY,
        # 【优化1】去掉宏观泛词，使用绝对硬核的垂直词组
        "query": "电竞行业 OR 网咖 OR 网吧 OR 电竞酒店 最新市场动态 新闻", 
        "search_depth": "basic",
        "topic": "news", 
        # 【优化2】放宽到过去7天，避免这两天没网吧新闻导致搜索引擎拿GDP、影院新闻凑数
        "days": 7,       
        "max_results": 5 
    }
    
    news_data =[]
    try:
        response = requests.post(url, json=payload, timeout=20)
        response.raise_for_status()
        results = response.json().get("results",[])
        
        for item in results:
            news_data.append({
                "title": item.get("title", "无标题"),
                "content": item.get("content", "无内容"), 
                "url": item.get("url", "#")
            })
        print(f"外部资讯获取完成，共抓取到 {len(news_data)} 条行业新闻。")
        return news_data
    except Exception as e:
        print(f"获取外部新闻失败: {e}")
        return[]

def generate_report_string(info_entries, news_entries):
    if not info_entries and not news_entries:
        return None
        
    internal_data_str = ""
    if info_entries:
        raw_texts =[f"[来源: {item.get('link') or '无'}]\n内容: {item.get('content', '')}" for item in info_entries]
        internal_data_str = "\n--------------------\n".join(raw_texts)
    else:
        internal_data_str = "今日暂无内部监测的视频观点信息更新。"

    external_data_str = ""
    if news_entries:
        news_texts =[f"[新闻标题]: {item['title']}\n[内容摘要]: {item['content']}\n[新闻来源]: {item['url']}" for item in news_entries]
        external_data_str = "\n--------------------\n".join(news_texts)
    else:
        external_data_str = "今日暂无获取到外部重大的行业新闻。"
    
    # 【优化3】在 Prompt 中赋予大模型绝对的“垃圾新闻否决权”
    prompt_template = """
你是一名资深的行业分析师，专注于中国【网咖、电竞场馆、电竞酒店、游戏】等线下娱乐行业。
今天你需要结合【内部监测视频内容】与【外部实时行业新闻】，生成一份高价值、具深度洞察的《电竞/网咖行业观点与动态日报》。

------------------------------------
【输入数据：第一部分 - 内部视频观点监测】
{internal_data}

【输入数据：第二部分 - 外部行业新闻追踪】
{external_data}
------------------------------------

【输出格式要求】
请严格按照以下两大核心模块输出日报内容：

一、 行业意见领袖观点（根据内部视频内容分析提取）
（注：若无内容直接写“今日暂无内部观点沉淀”）
要求：每位发布者单独列出，格式如下：
某某某认为：
* 观点 1（基于原始内容进行专业扩写成完整表达句）
* 观点 2（补充背景或推导行业逻辑）[观点来源](此处填入提供的链接)

二、 行业最新动态与新闻（根据外部新闻分析汇总）
⚠️⚠️⚠️【最高优先级指令】：你必须严格审查提供的“外部行业新闻追踪”数据。如果某条新闻与【电竞、网吧、网咖、电竞酒店、游戏行业】毫无直接关系（例如：传统影院破产、宏观GDP、通用AI企业、与游戏无关的制造业等），请【直接舍弃】该新闻，绝对不要生搬硬套！宁缺毋滥！
如果所有新闻都被判定为无关，本模块请直接输出一行字：“今日暂无高度相关的外部电竞/网咖行业动态。”

如果存在强相关新闻，请提取1-3条，格式如下：
1. 【提炼的核心新闻标题】
   - 核心摘要：简述新闻事件的核心要点。
   - 行业洞察：一句话点评该事件对中国网咖/电竞馆/电竞酒店行业老板的潜在影响或启发。
   [新闻来源](此处填入提供的链接)

注意：排版要清晰美观，重点突出能给网吧/电竞馆老板带来启发的商业逻辑。
"""
    final_prompt = prompt_template.format(
        internal_data=internal_data_str,
        external_data=external_data_str
    )

    print(f"\n正在请求 {CUSTOM_LLM_MODEL_ID} 模型生成综合日报...")
    try:
        client = OpenAI(base_url=CUSTOM_LLM_BASE_URL, api_key=CUSTOM_LLM_API_KEY)
        response = client.chat.completions.create(
            model=CUSTOM_LLM_MODEL_ID,
            messages=[{'role': 'user', 'content': final_prompt}],
            stream=False 
        )
        report_content = response.choices[0].message.content
        print("综合日报内容生成成功！")
        return report_content
    except Exception as e:
        print(f"调用大模型时发生错误: {e}")
        return None

def save_report_via_worker(report_content):
    if not report_content:
        return
        
    today_date = datetime.now().strftime('%Y-%m-%d')
    headers = {
        'X-Auth-Pass': CF_AUTH_SECRET, 
        'Content-Type': 'application/json'
    }
    payload = {'date': today_date, 'content': report_content}

    print(f"\n正在将报告发送到 {CF_WORKER_URL} ...")
    try:
        response = requests.post(CF_WORKER_URL, headers=headers, json=payload, timeout=30)
        if response.status_code == 200:
            print(f"报告保存成功！服务器响应: {response.json()}")
        else:
            print(f"保存失败 (状态码 {response.status_code})")
    except Exception as e:
        print(f"发送报告网络请求错误: {e}")

def main():
    print("--- 开始执行每日网咖/电竞行业综合简报生成任务 ---")
    if not check_env_vars():
        return

    token = get_tenant_access_token(APP_ID, APP_SECRET)
    info_entries = get_daily_info_with_links(token) if token else
