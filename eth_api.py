import os
import requests
import json
import logging
from datetime import datetime, timezone, timedelta
import openai # 导入新的库

# --- 日志配置 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- 从环境变量加载配置 ---
appID = os.getenv("APPID")
appSecret = os.getenv("APPSECRET")
openId = os.getenv("OPENID")
eth_template_id = os.getenv("ETH_TEMPLATE_ID")

# --- 新增：LLM (AI) 配置 ---
# 强烈建议将 LLM_API_KEY 存放在 GitHub Secrets 中，而不是直接写在代码里
llm_api_key = os.getenv("LLM_API_KEY", "AIzaSyBfaYYla_WbDyiula0MX7ZpRPChcVbWSx8")
llm_base_url = "https://gemini.zzh2025.dpdns.org/"
llm_model = "gemini-2.5-flash-lite"

# 初始化 LLM 客户端
# 检查 API Key 是否被设置，如果为空字符串则不初始化
if llm_api_key:
    try:
        llm_client = openai.OpenAI(
            api_key=llm_api_key,
            base_url=llm_base_url,
        )
    except Exception as e:
        logging.error(f"初始化 LLM 客户端失败: {e}")
        llm_client = None
else:
    logging.warning("LLM_API_KEY 环境变量未设置，将无法使用 AI 分析功能。")
    llm_client = None


# --- 历史数据文件配置 ---
HISTORY_FILE = 'eth_price_history.json'
MAX_HISTORY_POINTS = 300

if not all([appID, appSecret, openId, eth_template_id]):
    logging.error("缺少微信环境变量：请检查 APPID, APPSECRET, OPENID 和 ETH_TEMPLATE_ID 是否已正确设置")
    exit(1)

def fetch_eth_price_api() -> float | None:
    """使用 CoinGecko API 获取以太坊的实时美元价格。"""
    logging.info("fetch_eth_price_api 函数开始")
    url = "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        price = data.get('ethereum', {}).get('usd')
        
        if price is not None:
            price_float = float(price)
            logging.info(f"通过 API 成功获取以太坊价格: ${price_float}")
            return price_float
        else:
            logging.warning(f"API 响应中缺少价格数据。响应内容: {data}")
            return None
    except Exception as e:
        logging.error(f"通过 API 获取价格失败: {e}")
        return None
    finally:
        logging.info("fetch_eth_price_api 函数结束")

def get_access_token():
    """获取微信公众号的 access_token"""
    logging.info("get_access_token 函数开始")
    url = f'https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={appID.strip()}&secret={appSecret.strip()}'
    try:
        response = requests.get(url).json()
        access_token = response.get('access_token')
        if not access_token:
            logging.error(f"获取 access_token 失败: {response}")
            return None
        logging.info("成功获取 access_token")
        return access_token
    except Exception as e:
        logging.error(f"获取 access_token 过程中发生错误: {e}")
        return None
    finally:
        logging.info("get_access_token 函数结束")

def send_wechat_message(access_token, title, suggestion, price_info, remark):
    """发送包含分析建议的微信模板消息"""
    logging.info("send_wechat_message 函数开始")
    
    utc_now = datetime.now(timezone.utc)
    beijing_time = utc_now.astimezone(timezone(timedelta(hours=8)))
    formatted_time = beijing_time.strftime('%Y-%m-%d %H:%M:%S')

    body = {
        "touser": openId.strip(),
        "template_id": eth_template_id.strip(),
        "url": "https://www.coingecko.com/zh/%E6%95%B0%E5%AD%97%E8%B4%A7%E5%B8%81/%E4%BB%A5%E5%A4%AA%E5%9D%8A",
        "data": {
            "first": {"value": title, "color": "#173177"},
            "keyword1": {"value": price_info, "color": "#0000FF"},
            "keyword2": {"value": suggestion, "color": "#FF4500"},
            "remark": {"value": f"\n{remark}\n报告时间: {formatted_time}", "color": "#808080"}
        }
    }
    
    logging.info(f"准备发送消息体: {json.dumps(body, ensure_ascii=False)}")
    url = f'https://api.weixin.qq.com/cgi-bin/message/template/send?access_token={access_token}'
    try:
        response = requests.post(url, json=body)
        response.raise_for_status()
        logging.info(f"发送消息成功，微信服务器响应: {response.text}")
    except Exception as e:
        logging.error(f"发送消息到微信失败: {e}")
    finally:
        logging.info("send_wechat_message 函数结束")

def load_history():
    """从文件加载历史价格数据"""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logging.warning(f"无法加载或解析历史文件 '{HISTORY_FILE}': {e}。将创建新的历史记录。")
            return []
    return []

def save_history(history):
    """将历史价格数据保存到文件"""
    try:
        with open(HISTORY_FILE, 'w') as f:
            json.dump(history, f, indent=4)
        logging.info(f"成功将 {len(history)} 条记录保存到 '{HISTORY_FILE}'")
    except Exception as e:
        logging.error(f"无法保存历史文件 '{HISTORY_FILE}': {e}")


def analyze_with_llm(history, current_price):
    """
    使用 LLM 分析历史数据并给出买入/卖出建议。
    """
    if not llm_client:
        logging.warning("LLM 客户端未初始化，跳过 AI 分析。")
        return {"suggestion": "AI分析未启用", "reason": "LLM_API_KEY 未配置。"}

    # 为了节省 token，我们只传递最近的 100 个点给 LLM
    recent_history = history[-100:]
    
    # 构建给 LLM 的指令 (Prompt)
    prompt = f"""
    你是一名专业的加密货币数据分析师。请根据下面提供的以太坊（ETH）历史价格数据和当前最新价格，给出一个简明扼要的投资建议。

    要求：
    1. 你的核心任务是判断当前趋势，并给出明确的指令：'买入'、'卖出' 或 '观望'。
    2. 提供一个不超过30个字的简短理由来支撑你的建议。
    3. 你的回答必须是严格的 JSON 格式，包含两个键： "suggestion" 和 "reason"。

    历史价格数据（部分，按时间顺序排列）：
    {json.dumps(recent_history, indent=2)}

    当前最新价格：
    ${current_price:,.2f}

    请根据以上所有信息，给出你的专业分析。
    """

    try:
        logging.info("开始调用 LLM进行分析...")
        chat_completion = llm_client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": "你是一名专业的加密货币数据分析师，你的回答必须是严格的 JSON 格式。",
                },
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            model=llm_model,
            response_format={"type": "json_object"}, # 强制要求 JSON 输出
            temperature=0.3, # 让模型输出更稳定
        )
        
        response_content = chat_completion.choices[0].message.content
        logging.info(f"成功获取 LLM 分析结果: {response_content}")
        
        # 解析 LLM 返回的 JSON 字符串
        analysis = json.loads(response_content)
        return analysis

    except Exception as e:
        logging.error(f"调用 LLM API 或解析结果失败: {e}")
        return {"suggestion": "AI分析失败", "reason": "调用模型时发生错误，请检查服务状态或API密钥。"}


def eth_report():
    """主任务函数：获取价格、分析并根据条件发送报告"""
    logging.info("eth_report 函数开始")
    
    access_token = get_access_token()
    if not access_token:
        logging.error("无法获取 access_token，任务终止")
        return

    eth_price_float = fetch_eth_price_api()
    if eth_price_float is None:
        send_wechat_message(access_token, "运行失败", "未能获取以太坊价格", "N/A", "请检查网络或API状态。")
        return

    history = load_history()
    
    current_time = datetime.now(timezone.utc).isoformat()
    history.append({"timestamp": current_time, "price": eth_price_float})
    
    if len(history) > MAX_HISTORY_POINTS:
        history = history[-MAX_HISTORY_POINTS:]

    # 使用新的 LLM 函数进行分析
    analysis = analyze_with_llm(history, eth_price_float)
    
    save_history(history)
    
    # 准备并发送消息
    formatted_price = f"${eth_price_float:,.2f}"
    price_info = f"当前价格: {formatted_price}"
    title = f"ETH AI 分析报告：{analysis.get('suggestion', 'N/A')}"
    suggestion = analysis.get('suggestion', '分析无结果')
    remark = analysis.get('reason', '未能获取分析详情。')
    
    # 检查是否触发价格预警，预警信息优先
    if eth_price_float < 2100 or eth_price_float > 3800:
        title = f"价格预警！ETH 现价 {formatted_price}"
        logging.info(f"价格触发提醒条件 (< 2100 or > 3800)。")
    
    send_wechat_message(access_token, title, suggestion, price_info, remark)

    logging.info("eth_report 函数结束")

if __name__ == "__main__":
    logging.info("__main__ 开始")
    eth_report()
    logging.info("__main__ 结束")
