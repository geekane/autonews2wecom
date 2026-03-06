import os
import requests
import json
import time
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
CUSTOM_LLM_MODEL_ID = "gemini-3.1-flash-lite" 
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
    required_vars = [
        "FEISHU_APP_ID", "FEISHU_APP_SECRET",
        "CF_WORKER_URL", "TAVILY_API_KEY"
    ]
    missing_vars = [var for var in required_vars if not os.environ.get(var)]
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
    text_parts = []
    for item in field_value:
        if item.get("type") == "text":
            text_parts.append(item.get("text", ""))
    return "".join(text_parts)

def get_daily_info_with_links(access_token):
    headers = {'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'}
    info_data = []
    page_token = ""
    print("\n开始查询飞书最近1天的内部信息内容...")
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
        except Exception as e:
            print(f"查询记录时网络请求失败: {e}")
            break
    print(f"飞书查询完成，共找到 {len(info_data)} 条内部观点。")
    return info_data

def get_industry_news():
    """
    【升级版】多维度组合搜索：
    1. 行业动态（网咖/电竞酒店）
    2. 硬件资讯（显卡/外设）
    3. 热门游戏（流量来源）
    """
    print("\n开始通过 Tavily 进行多维度挖掘...")
    
    # 定义三个维度的搜索词
    search_queries = [
        "中国 电竞酒店 网咖 网吧 行业趋势 经营 倒闭 政策",  # 行业
        "NVIDIA 显卡 新品 机械键盘 鼠标 电竞显示器 硬件",   # 硬件 (网吧核心成本)
        "热门电竞游戏 英雄联盟 瓦洛兰特 绝地求生 Steam热销榜" # 游戏 (网吧核心流量)
    ]
    
    all_news = []
    seen_urls = set() # 用于去重
    
    url = "https://api.tavily.com/search"
    
    for query in search_queries:
        print(f"正在检索维度: [{query}] ...")
        payload = {
            "api_key": TAVILY_API_KEY,
            "query": query,
            "search_depth": "basic",
            "topic": "news", 
            "days": 5,       # 获取最近5天
            "max_results": 4 # 每个维度取4条，合计约12条
        }
        
        try:
            response = requests.post(url, json=payload, timeout=20)
            response.raise_for_status()
            results = response.json().get("results", [])
            
            for item in results:
                link = item.get("url")
                # 简单去重：如果这个链接已经抓过，就跳过
                if link and link not in seen_urls:
                    seen_urls.add(link)
                    all_news.append({
                        "title": item.get("title", "无标题"),
                        "content": item.get("content", "无内容"), 
                        "url": link,
                        "category": query # 标记一下来源维度，方便大模型识别
                    })
            
            # 稍微停顿一下，防止并发太快
            time.sleep(1) 
            
        except Exception as e:
            print(f"维度 [{query}] 检索失败: {e}")
            
    print(f"外部资讯挖掘完成，去重后共获得 {len(all_news)} 条素材。")
    return all_news

def generate_report_string(info_entries, news_entries):
    if not info_entries and not news_entries:
        return None
        
    internal_data_str = ""
    if info_entries:
        raw_texts = [f"[来源: {item.get('link') or '无'}]\n内容: {item.get('content', '')}" for item in info_entries]
        internal_data_str = "\n--------------------\n".join(raw_texts)
    else:
        internal_data_str = "今日暂无内部监测的视频观点信息更新。"

    external_data_str = ""
    if news_entries:
        # 将多维度的素材全部喂给大模型
        news_texts = []
        for item in news_entries:
            news_texts.append(f"[分类]: {item.get('category')}\n[标题]: {item['title']}\n[摘要]: {item['content']}\n[链接]: {item['url']}")
        external_data_str = "\n--------------------\n".join(news_texts)
    else:
        external_data_str = "今日暂无获取到外部重大的行业新闻。"
    
    # 【Prompt 升级】明确指示 AI 关注硬件和游戏
    prompt_template = """
你是一名中国网咖/电竞酒店行业的资深经营顾问。
今天你需要结合【内部监测观点】与【全网多维度资讯】，为老板们生成一份《电竞实体经营参考日报》。

------------------------------------
【内部观点素材】
{internal_data}

【全网资讯素材库 (包含行业、硬件、游戏三类)】
{external_data}
------------------------------------

【输出指令】
请从素材库中智能筛选出 **最能影响网吧老板赚钱** 的 5-7 条信息。
筛选标准：
1. **硬件行情**：是否有新显卡/CPU发布（影响采购成本）？
2. **游戏风向**：是否有新爆款游戏或赛事（影响上座率）？
3. **行业红线**：是否有未成年人监管等新规（影响生存）？
❌ 剔除：传统的电影院新闻、宏观GDP数据、与线下实体无关的纯科技新闻。

【输出格式】

### 一、 内部洞察（基于视频监测）
（若无内容写“今日暂无内部观点”）
* **某某某**：[观点摘要] [来源链接]

### 二、 市场与硬件情报（精选外部资讯）
1. **【硬件/装备】标题**
   * *情报*: 简述新闻（如：RTX5090发布时间曝光）。
   * *老板参谋*: 这意味着什么？（如：建议暂缓大规模更新显卡，等待降价）。
   [来源](链接)

2. **【游戏/流量】标题**
   * *情报*: 简述（如：瓦洛兰特新赛季热度飙升）。
   * *老板参谋*: 建议（如：尽快更新游戏补丁，举办店内小型比赛拉客）。
   [来源](链接)

3. **【行业/政策】标题**
   * ...

(请确保选出的新闻对网咖经营者有实际参考价值，语气专业且务实)
"""
    final_prompt = prompt_template.format(
        internal_data=internal_data_str,
        external_data=external_data_str
    )

    print(f"\n正在请求 {CUSTOM_LLM_MODEL_ID} 模型进行智能筛选与撰写...")
    try:
        client = OpenAI(base_url=CUSTOM_LLM_BASE_URL, api_key=CUSTOM_LLM_API_KEY)
        response = client.chat.completions.create(
            model=CUSTOM_LLM_MODEL_ID,
            messages=[{'role': 'user', 'content': final_prompt}],
            stream=False 
        )
        report_content = response.choices[0].message.content
        print("日报生成成功！")
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
    print("--- 开始执行每日网咖经营情报任务 ---")
    if not check_env_vars():
        return

    token = get_tenant_access_token(APP_ID, APP_SECRET)
    info_entries = get_daily_info_with_links(token) if token else []

    news_entries = get_industry_news()

    report_content = generate_report_string(info_entries, news_entries)
    
    save_report_via_worker(report_content)
    
    print("\n--- 任务执行完毕 ---")

if __name__ == "__main__":
    main()
