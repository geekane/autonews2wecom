import os
import requests
import json
from datetime import datetime
from openai import OpenAI

# ==========================================
# 1. 配置信息
# ==========================================
APP_ID = os.environ.get("FEISHU_APP_ID")
APP_SECRET = os.environ.get("FEISHU_APP_SECRET")
APP_TOKEN = "BJ2gbK1onahpjZsglTgcxo7Onif" 
TABLE_ID = "tbliEUHB9iSxZuiY" 

CF_WORKER_URL = os.environ.get("CF_WORKER_URL")
CF_AUTH_SECRET = os.environ.get("CF_AUTH_SECRET", "1234")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")

# 自定义 Gemini LLM 配置
CUSTOM_LLM_API_KEY = "123456" 
CUSTOM_LLM_MODEL_ID = "gemini-2.5-flash-lite" 
CUSTOM_LLM_BASE_URL = "https://aiclient-2-api-89ny.onrender.com/v1"

TENANT_ACCESS_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal/"
SEARCH_RECORDS_URL = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records/search"

# ==========================================
# 2. 功能函数
# ==========================================
def check_env_vars():
    required = ["FEISHU_APP_ID", "FEISHU_APP_SECRET", "CF_WORKER_URL", "TAVILY_API_KEY"]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        print(f"错误: 缺环境变量 {', '.join(missing)}")
        return False
    return True

def get_tenant_access_token(app_id, app_secret):
    try:
        url = TENANT_ACCESS_TOKEN_URL
        resp = requests.post(url, json={"app_id": app_id, "app_secret": app_secret})
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") == 0:
            return data.get("tenant_access_token")
        print(f"获取Token失败: {data.get('msg')}")
    except Exception as e:
        print(f"Token网络错误: {e}")
    return None

def parse_rich_text(field_value):
    if not isinstance(field_value, list): return str(field_value)
    return "".join([item.get("text", "") for item in field_value if item.get("type") == "text"])

def get_daily_info_with_links(access_token):
    headers = {'Authorization': f'Bearer {access_token}'}
    info_data = []
    page_token = ""
    print("查询飞书内部数据...")
    while True:
        payload = {
            "filter": {
                "conjunction": "and", 
                "conditions":[{"field_name": "发布日期", "operator": "is", "value": ["Yesterday"]}] 
            },
            "field_names":["完整信息内容", "视频链接"],
            "page_size": 100,
            "page_token": page_token
        }
        try:
            resp = requests.post(SEARCH_RECORDS_URL, json=payload, headers=headers)
            data = resp.json().get("data", {})
            items = data.get("items", [])
            if not items and not page_token: break
            
            for item in items:
                fields = item.get('fields', {})
                content = fields.get('完整信息内容')
                if content:
                    info_data.append({
                        "content": parse_rich_text(content).strip(),
                        "link": fields.get('视频链接')
                    })
            
            if data.get('has_more'): page_token = data.get('page_token')
            else: break
        except Exception as e:
            print(f"飞书查询出错: {e}")
            break
    print(f"找到 {len(info_data)} 条内部观点")
    return info_data

def get_industry_news():
    print("查询外部行业新闻...")
    try:
        # 优化搜索词，去掉宏观泛词，锁定垂直领域
        payload = {
            "api_key": TAVILY_API_KEY,
            "query": "电竞馆 OR 网咖 OR 网吧 OR 电竞酒店 市场动态 经营新闻", 
            "topic": "news", 
            "days": 5,  # 放宽到5天，确保有相关内容
            "max_results": 5 
        }
        resp = requests.post("https://api.tavily.com/search", json=payload, timeout=20)
        results = resp.json().get("results", [])
        print(f"抓取到 {len(results)} 条外部新闻")
        return [{"title": i.get("title"), "content": i.get("content"), "url": i.get("url")} for i in results]
    except Exception as e:
        print(f"新闻获取失败: {e}")
        return []

def generate_report_string(info_entries, news_entries):
    if not info_entries and not news_entries: return None
    
    internal_str = "\n".join([f"- 内容: {i['content']} [链接]({i['link'] or ''})" for i in info_entries]) if info_entries else "今日无内部观点。"
    external_str = "\n".join([f"- {n['title']}: {n['content']} [来源]({n['url']})" for n in news_entries]) if news_entries else "今日无外部新闻。"

    # 提示词：加入严格过滤指令
    prompt = f"""
你是一名专注于中国【网咖、电竞馆、电竞酒店】行业的分析师。请基于以下数据生成日报。

【内部数据】
{internal_str}

【外部新闻】
{external_str}

【严格指令】
1. 必须生成两个板块：一、行业意见领袖观点；二、行业最新动态。
2. **外部新闻过滤**：如果外部新闻包含“电影院破产”、“宏观GDP”、“通用AI技术”、“纯制造业”等与网吧/电竞经营**无关**的内容，请**直接忽略**，不要写入日报。
3. 只保留与“网咖、电竞馆、游戏、电竞酒店”强相关的新闻。
4. 格式：
   一、 行业意见领袖观点
   某某某认为：
   * 观点... [来源](链接)

   二、 行业最新动态
   1. 【标题】
      - 摘要...
      - 洞察：对网咖老板的启示...
      [来源](链接)
"""
    print(f"请求 LLM ({CUSTOM_LLM_MODEL_ID})...")
    try:
        client = OpenAI(base_url=CUSTOM_LLM_BASE_URL, api_key=CUSTOM_LLM_API_KEY)
        resp = client.chat.completions.create(
            model=CUSTOM_LLM_MODEL_ID,
            messages=[{'role': 'user', 'content': prompt}],
            stream=False 
        )
        return resp.choices[0].message.content
    except Exception as e:
        print(f"LLM 错误: {e}")
        return None

def save_report_via_worker(content):
    if not content: return
    print(f"发送报告到 Cloudflare...")
    try:
        headers = {'X-Auth-Pass': CF_AUTH_SECRET, 'Content-Type': 'application/json'}
        payload = {'date': datetime.now().strftime('%Y-%m-%d'), 'content': content}
        requests.post(CF_WORKER_URL, headers=headers, json=payload, timeout=30)
        print("发送成功")
    except Exception as e:
        print(f"发送失败: {e}")

# ==========================================
# 3. 主程序
# ==========================================
def main():
    print("--- 任务开始 ---")
    if not check_env_vars(): return

    # 1. 获取Token
    token = get_tenant_access_token(APP_ID, APP_SECRET)
    
    # 2. 获取数据 (修复了之前的语法错误)
    info_entries = get_daily_info_with_links(token) if token else []
    news_entries = get_industry_news()

    # 3. 生成报告
    report = generate_report_string(info_entries, news_entries)
    
    # 4. 保存
    save_report_via_worker(report)
    print("--- 任务结束 ---")

if __name__ == "__main__":
    main()
