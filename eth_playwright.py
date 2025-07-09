import os
import requests
import json
import logging
# 注意这里引入了 PlaywrightTimeoutError
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ... (前面的配置和环境变量检查代码保持不变) ...

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 从环境变量中获取测试号信息
appID = os.getenv("APPID")
appSecret = os.getenv("APPSECRET")
openId = os.getenv("OPENID")
eth_template_id = os.getenv("ETH_TEMPLATE_ID")

if not all([appID, appSecret, openId, eth_template_id]):
    logging.error("缺少环境变量：请检查 APPID, APPSECRET, OPENID 和 ETH_TEMPLATE_ID 是否已正确设置")
    exit(1)

def fetch_eth_price(url: str, wait_time: int = 60) -> str | None:
    """
    使用 Playwright 获取动态渲染的页面并提取以太坊价格。
    """
    logging.info("fetch_eth_price 函数开始 (使用 Playwright)")
    
    with sync_playwright() as p:
        browser = None # 确保 browser 变量在 try 外部定义
        try:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            )
            page = context.new_page()
            page.goto(url, wait_until='domcontentloaded', timeout=wait_time * 1000)

            # ⬇️⬇️⬇️  这是唯一的修改点 ⬇️⬇️⬇️
            # 在定位器后面加上 .first 来确保我们只选择匹配到的第一个元素，避免严格模式冲突
            price_locator = page.locator(
                '//span[@data-converter-target="price"][@data-coin-id="279"][@data-price-target="price"]'
            ).first
            # ⬆️⬆️⬆️  修改结束 ⬆️⬆️⬆️
            
            # 等待元素可见
            price_locator.wait_for(state='visible', timeout=wait_time * 1000)

            price = price_locator.inner_text()
            logging.info(f"成功获取以太坊价格: {price}")
            
            browser.close()
            return price

        except PlaywrightTimeoutError as e:
            # 使错误日志更具体
            logging.error(f"等待或定位价格元素时超时或出错: {e}")
            try:
                # 检查页面是否存在再截图
                if 'page' in locals():
                    page.screenshot(path="error_playwright.png")
                    logging.info("已保存错误截图到 error_playwright.png")
            except Exception as screenshot_e:
                logging.error(f"保存截图失败: {screenshot_e}")
            if browser and browser.is_connected():
                browser.close()
            return None
        except Exception as e:
            logging.error(f"使用 Playwright 获取页面信息失败: {e}")
            if browser and browser.is_connected():
                browser.close()
            return None
    
    logging.info("fetch_eth_price 函数结束")

# ... (get_access_token, send_wechat_message, eth_report 和 main 部分保持不变) ...
def get_access_token():
    logging.info("get_access_token 函数开始")
    url = f'https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={appID.strip()}&secret={appSecret.strip()}'
    try:
        response = requests.get(url).json()
        logging.info(f"get_access_token 响应: {response}")
        access_token = response.get('access_token')
        if not access_token:
            logging.error(f"获取 access_token 失败: {response}")
            return None
        logging.info(f"成功获取 access_token")
        return access_token
    except requests.exceptions.RequestException as e:
        logging.error(f"获取 access_token 失败: 网络请求错误: {e}")
        return None
    except json.JSONDecodeError as e:
        logging.error(f"解析 JSON 响应失败: {e}")
        return None
    finally:
        logging.info("get_access_token 函数结束")

def send_wechat_message(access_token, message):
    logging.info("send_wechat_message 函数开始")
    body = {
        "touser": openId.strip(),
        "template_id": eth_template_id.strip(),
        "url": "https://weixin.qq.com",
        "data": {
            "ETH": {"value": message}
        }
    }
    logging.info(f"准备发送消息体: {body}")
    url = f'https://api.weixin.qq.com/cgi-bin/message/template/send?access_token={access_token}'
    try:
        response = requests.post(url, json=body)
        response.raise_for_status()
        logging.info(f"发送消息成功，微信服务器响应: {response.text}")
    except requests.exceptions.RequestException as e:
        logging.error(f"发送消息到微信失败: 网络请求错误: {e}")
        logging.error(f"失败的消息体: {body}")
    except Exception as e:
        logging.error(f"发送消息到微信失败: {e}")
        logging.error(f"失败的消息体: {body}")
    finally:
        logging.info("send_wechat_message 函数结束")

def eth_report():
    logging.info("eth_report 函数开始")
    access_token = get_access_token()
    if not access_token:
        logging.error("无法获取 access_token，任务终止")
        return

    url = 'https://www.coingecko.com/zh/%E6%95%B0%E5%AD%97%E8%B4%A7%E5%B8%81/%E4%BB%A5%E5%A4%AA%E5%9D%8A'
    eth_price_str = fetch_eth_price(url)
    logging.info(f"获取到的原始价格字符串: {eth_price_str}")

    if eth_price_str:
        try:
            price_cleaned = ''.join(filter(lambda x: x in '0123456789.', eth_price_str))
            price_float = float(price_cleaned)
            logging.info(f"转换后的价格 (float): {price_float}")

            if price_float < 2100 or price_float > 2500:
                logging.info(f"价格 {price_float} 触发提醒条件 (< 2100 or > 2500)。准备发送提醒。")
                message = f"当前价格: {eth_price_str}，已触发预警！"
                send_wechat_message(access_token, message)
            else:
                logging.info(f"当前价格 {price_float} 在正常范围内 (2100-2500)，不发送提醒。")

        except (ValueError, TypeError) as e:
            logging.error(f"无法将价格字符串 '{eth_price_str}' 转换为数字: {e}")
            error_message = f"获取价格成功，但格式无法解析: {eth_price_str}"
            send_wechat_message(access_token, error_message)
    else:
        send_wechat_message(access_token, "运行失败，未能获取以太坊价格")

    logging.info("eth_report 函数结束")

if __name__ == "__main__":
    logging.info("__main__ 开始")
    eth_report()
    logging.info("__main__ 结束")
