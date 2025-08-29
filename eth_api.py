import os
import requests
import json
import logging
from datetime import datetime, timezone, timedelta
import openai

# --- 日志配置 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- 从环境变量加载配置 ---
appID = os.getenv("APPID")
appSecret = os.getenv("APPSECRET")
openId = os.getenv("OPENID")
eth_template_id = os.getenv("ETH_TEMPLATE_ID")

# --- LLM (AI) 配置 ---
llm_api_key = os.getenv("LLM_API_KEY", "AIzaSyBfaYYla_WbDyiula0MX7ZpRPChcVbWSx8")
llm_base_url = "https://gemini.zzh2025.dpdns.org/"
llm_model = "gemini-2.5-flash-lite"

# --- 历史数据文件配置 ---
HISTORY_FILE = 'eth_price_history.json'
MAX_HISTORY_POINTS = 300

# --- 初始化 LLM 客户端 ---
if llm_api_key:
    try:
        llm_client = openai.OpenAI(api_key=llm_api_key, base_url=llm_base_url)
    except Exception as e:
        logging.error(f"初始化 LLM 客户端失败: {e}")
        llm_client = None
else:
    logging.warning("LLM_API_KEY 环境变量未设置，将无法使用 AI 分析功能。")
    llm_client = None

if not all([appID, appSecret, openId, eth_template_id]):
    logging.error("缺少微信环境变量，请检查配置")
    exit(1)

# ==============================================================================
#  核心函数定义区
# ==============================================================================

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

def send_wechat_message(access_token, title, product_name, current_price, suggestion, remark_details):
    """发送微信模板消息 (最终简化版)"""
    logging.info("send_wechat_message 函数开始 (最终简化版)")
    
    body = {
        "touser": openId.strip(),
        "template_id": eth_template_id.strip(),
        "url": "https://www.coingecko.com/zh/%E6%95%B0%E5%AD%97%E8%B4%A7%E5%B8%81/%E4%BB%A5%E5%A4%AA%E5%9D%8A",
        "data": {
            "keyword1": { "value": product_name },
            "keyword2": { "value": current_price },
            "keyword3": { "value": suggestion },
            # --- 核心修改：remark 的值直接使用 AI 返回的理由 ---
            "remark": { "value": remark_details }
        }
    }
    
    logging.info(f"准备发送消息体: {json.dumps(body, ensure_ascii=False, indent=2)}")
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
    """使用 LLM 分析历史数据并给出买入/卖出建议。"""
    if not llm_client:
        logging.warning("LLM 客户端未初始化，跳过 AI 分析。")
        return {"suggestion": "AI分析未启用", "reason": "LLM_API_KEY 未配置。"}

    recent_history = history[-100:]
    
    prompt = f"""
    **任务：**
    作为一名专业的加密货币数据分析师，你的任务是分析给定的以太坊(ETH)历史价格数据和当前价格，并输出一个包含投资建议的JSON对象。

    **输入数据：**
    1.  **历史价格 (部分):**
        ```json
        {json.dumps(recent_history, indent=2)}
        ```
    2.  **当前价格:** ${current_price:,.2f}

    **输出要求：**
    你的输出**必须**是一个严格的JSON对象。JSON对象必须包含以下两个键：
    -   `"suggestion"`: 值为 "买入", "卖出", 或 "观望" 中的一个。
    -   `"reason"`: 一个非常精炼的中文理由，**严格控制在20个字以内**，例如 "价格近期小幅上涨后稳定，数据有限，等待更明确趋势"。

    **输出示例：**
    ```json
    {{
      "suggestion": "观望",
      "reason": "价格近期小幅上涨后稳定，等待更明确趋势。"
    }}
    ```

    请严格按照要求执行分析并返回结果。
    """

    try:
        logging.info("开始调用 LLM进行分析...")
        chat_completion = llm_client.chat.completions.create(
            messages=[
                {"role": "system", "content": "你是一个只输出指定格式JSON的加密货币分析机器人。"},
                {"role": "user", "content": prompt}
            ],
            model=llm_model,
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        
        logging.info(f"收到的原始 chat_completion 对象: {chat_completion}")

        message_obj = None
        if chat_completion.choices and isinstance(chat_completion.choices[0], list):
             if chat_completion.choices[0]:
                 message_obj = chat_completion.choices[0][0].message
        elif chat_completion.choices:
             message_obj = chat_completion.choices[0].message
        
        if not message_obj:
            raise ValueError("AI 返回了空的 message 对象")

        response_content = message_obj.content
        logging.info(f"成功提取 LLM 分析结果: {response_content}")
        
        start_index = response_content.find('{')
        end_index = response_content.rfind('}')
        if start_index != -1 and end_index != -1 and start_index < end_index:
            clean_json_str = response_content[start_index : end_index + 1]
            analysis = json.loads(clean_json_str)
            
            if 'suggestion' in analysis and 'reason' in analysis:
                logging.info("JSON 结构验证通过，包含 suggestion 和 reason。")
                return analysis
            else:
                logging.error(f"AI返回的JSON结构不正确，缺少必要的键。收到: {analysis}")
                raise ValueError("AI返回的JSON结构不正确")
        else:
            raise json.JSONDecodeError("在模型响应中未找到有效的JSON对象", response_content, 0)

    except Exception as e:
        logging.error(f"调用 LLM API 或解析结果失败: {e}")
        return {"suggestion": "AI分析失败", "reason": "调用模型时发生错误，请检查服务状态或API密钥。"}

# ==============================================================================
#  主逻辑执行区
# ==============================================================================

def eth_report():
    """主任务函数：获取价格、分析并根据条件发送报告"""
    logging.info("eth_report 函数开始")
    
    access_token = get_access_token()
    if not access_token:
        logging.error("无法获取 access_token，任务终止")
        return

    eth_price_float = fetch_eth_price_api()
    history = load_history()
    
    if eth_price_float is None:
        save_history(history)
        send_wechat_message(access_token, "运行失败", "以太坊 (ETH)", "N/A", "未能获取价格", "请检查网络或API状态。")
        return

    current_time = datetime.now(timezone.utc).isoformat()
    history.append({"timestamp": current_time, "price": eth_price_float})
    
    if len(history) > MAX_HISTORY_POINTS:
        history = history[-MAX_HISTORY_POINTS:]

    analysis = analyze_with_llm(history, eth_price_float)
    
    save_history(history)
    
    # 准备发送给微信的数据
    formatted_price = f"${eth_price_float:,.2f}"
    product_name = "以太坊 (ETH)"
    current_price_val = formatted_price
    suggestion = analysis.get('suggestion', '分析无结果')
    remark_details = analysis.get('reason', '未能获取分析详情。')
    
    title = f"ETH AI 分析报告：{suggestion}"
    if eth_price_float < 2100 or eth_price_float > 3800:
        title = f"价格预警！ETH 现价 {formatted_price}"
        logging.info(f"价格触发提醒条件 (< 2100 or > 3800)。")
    
    send_wechat_message(access_token, title, product_name, current_price_val, suggestion, remark_details)
    logging.info("eth_report 函数结束")

if __name__ == "__main__":
    logging.info("__main__ 开始")
    eth_report()
    logging.info("__main__ 结束")
