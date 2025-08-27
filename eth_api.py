import os
import requests
import json
import logging

# --- 日志配置 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- 从环境变量加载配置 ---
appID = os.getenv("APPID")
appSecret = os.getenv("APPSECRET")
openId = os.getenv("OPENID")
eth_template_id = os.getenv("ETH_TEMPLATE_ID")

if not all([appID, appSecret, openId, eth_template_id]):
    logging.error("缺少环境变量：请检查 APPID, APPSECRET, OPENID 和 ETH_TEMPLATE_ID 是否已正确设置")
    exit(1)

def fetch_eth_price_api() -> float | None:
    """
    使用 CoinGecko API 获取以太坊的实时美元价格。
    如果成功，返回一个浮点数；如果失败，返回 None。
    """
    logging.info("fetch_eth_price_api 函数开始 (使用 API)")
    url = "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd"
    try:
        # 设置10秒超时，避免请求卡死
        response = requests.get(url, timeout=10)
        # 如果HTTP状态码不是2xx，则抛出异常
        response.raise_for_status()
        data = response.json()
        
        # 安全地获取价格，避免因API响应格式变化而出错
        price = data.get('ethereum', {}).get('usd')
        
        if price is not None:
            price_float = float(price)
            logging.info(f"通过 API 成功获取以太坊价格: ${price_float}")
            return price_float
        else:
            logging.warning(f"API 响应中缺少价格数据。响应内容: {data}")
            return None
            
    except requests.exceptions.RequestException as e:
        logging.error(f"通过 API 获取价格失败: 网络请求错误: {e}")
        return None
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logging.error(f"解析 API 响应或转换价格失败: {e}")
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
    except requests.exceptions.RequestException as e:
        logging.error(f"获取 access_token 失败: 网络请求错误: {e}")
        return None
    except json.JSONDecodeError as e:
        logging.error(f"解析 get_access_token 的 JSON 响应失败: {e}")
        return None
    finally:
        logging.info("get_access_token 函数结束")

def send_wechat_message(access_token, message):
    """发送微信模板消息"""
    logging.info("send_wechat_message 函数开始")
    body = {
        "touser": openId.strip(),
        "template_id": eth_template_id.strip(),
        "url": "https://www.coingecko.com/zh/%E6%95%B0%E5%AD%97%E8%B4%A7%E5%B8%81/%E4%BB%A5%E5%A4%AA%E5%9D%8A", # URL可以改为CoinGecko页面
        "data": {
            "ETH": {"value": message}
        }
    }
    logging.info(f"准备发送消息体: {json.dumps(body, ensure_ascii=False)}")
    url = f'https://api.weixin.qq.com/cgi-bin/message/template/send?access_token={access_token}'
    try:
        response = requests.post(url, json=body)
        response.raise_for_status()
        logging.info(f"发送消息成功，微信服务器响应: {response.text}")
    except requests.exceptions.RequestException as e:
        logging.error(f"发送消息到微信失败: 网络请求错误: {e}")
        logging.error(f"失败的消息体: {json.dumps(body, ensure_ascii=False)}")
    finally:
        logging.info("send_wechat_message 函数结束")

def eth_report():
    """主任务函数：获取价格并根据条件发送报告"""
    logging.info("eth_report 函数开始")
    access_token = get_access_token()
    if not access_token:
        logging.error("无法获取 access_token，任务终止")
        return

    # 调用新的API函数获取价格
    eth_price_float = fetch_eth_price_api()

    if eth_price_float is not None:
        # 直接使用获取到的浮点数进行判断
        if eth_price_float < 2100 or eth_price_float > 3800:
            logging.info(f"价格 ${eth_price_float} 触发提醒条件 (< 2100 or > 3800)。准备发送提醒。")
            
            # 格式化价格，使其更易读 (例如: $3,456.78)
            formatted_price = f"${eth_price_float:,.2f}"
            message = f"当前价格: {formatted_price}，已触发预警！"
            send_wechat_message(access_token, message)
        else:
            logging.info(f"当前价格 ${eth_price_float} 在正常范围内 (2100-3800)，不发送提醒。")
    else:
        # 如果获取价格失败
        send_wechat_message(access_token, "运行失败，未能获取以太坊价格")

    logging.info("eth_report 函数结束")

if __name__ == "__main__":
    logging.info("__main__ 开始")
    eth_report()
    logging.info("__main__ 结束")
