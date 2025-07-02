import argparse
import os
import platform
import requests
import json  # 添加 json 模块导入
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 从环境变量中获取测试号信息
appID = os.getenv("APPID")
appSecret = os.getenv("APPSECRET")
openId = os.getenv("OPENID")
eth_template_id = os.getenv("ETH_TEMPLATE_ID")

if not appID or not appSecret or not openId or not eth_template_id:
    print("缺少环境变量：请检查 APPID, APPSECRET, OPENID 和 ETH_TEMPLATE_ID 是否已正确设置")
    exit()

def fetch_eth_price(url, driver_path=None, chromium_path=None, wait_time=60):
    """
    使用 Selenium 获取动态渲染的页面 HTML 并提取以太坊价格。

    Args:
        url (str): 要抓取的 URL。
        driver_path (str, optional): ChromeDriver 的路径。如果为 None，则使用当前目录下的 chromedriver。
        chromium_path (str, optional): Chromium 浏览器的路径。
        wait_time (int, optional): 等待页面元素加载的最长时间（秒）。

    Returns:
        str: 以太坊价格，如果获取失败则返回 None。
    """
    logging.info("fetch_eth_price 函数开始")  # 使用 logging 记录函数开始

    driver = None  # 确保 driver 在 try 块之外声明
    try:
        chrome_options = Options()
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
        if chromium_path:
            chrome_options.binary_location = chromium_path

        # 使用 try-except 处理 chromedriver 路径问题
        try:
            if driver_path:
                service = ChromeService(executable_path=driver_path)
            else:
                current_dir = os.path.dirname(os.path.abspath(__file__))
                driver_path = os.path.join(current_dir, 'chromedriver')
                if not os.path.exists(driver_path):
                    raise FileNotFoundError(f"chromedriver not found at: {driver_path}") # 抛出异常，更好地处理错误
                service = ChromeService(executable_path=driver_path)
        except FileNotFoundError as e:
            logging.error(e)
            return None
        except Exception as e:
            logging.error(f"初始化 ChromeDriver 服务失败: {e}")
            return None

        logging.info(f"Using chromedriver at: {driver_path}")
        logging.info(f"Python architecture: {platform.architecture()}")

        driver = webdriver.Chrome(service=service, options=chrome_options) # 初始化 ChromeDriver
        driver.get(url)

        try:
            # 使用更具体的 XPath，提高定位准确性
            element = WebDriverWait(driver, wait_time).until(
                EC.presence_of_element_located(
                    (By.XPATH, '//span[@data-converter-target="price"][contains(@data-coin-id, "279")][@data-price-target="price"]')
                )
            )
            if not element.is_displayed():
                logging.warning("元素存在，但不可见")
                logging.warning(f"CSS display 属性: {element.value_of_css_property('display')}")
                logging.warning(f"CSS visibility 属性: {element.value_of_css_property('visibility')}")

        except Exception as e:
            logging.error(f"等待价格元素加载失败: {e}")
            try:
                driver.save_screenshot("error.png")
                logging.info("已保存错误截图到 error.png")
            except Exception as screenshot_e:
                logging.error(f"保存截图失败: {screenshot_e}")
            return None

        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')

        # 使用相同的 XPath 提取价格
        price_span = soup.find('span', attrs={'data-converter-target': 'price', 'data-coin-id': '279', 'data-price-target': 'price'}) #soup.find('span', attrs={'data-converter-target': 'price'})
        if price_span:
            price = price_span.text.strip()
            logging.info(f"以太坊价格: {price}")
            return price
        else:
            logging.warning("获取价格失败: 未找到价格 span")
            return None

    except Exception as e:
        logging.error(f"获取页面信息失败: {e}")
        return None

    finally:
        if driver: # 确保 driver 已经初始化
            try:
                driver.quit()
            except Exception as e:
                logging.error(f"关闭 ChromeDriver 失败: {e}")
        logging.info("fetch_eth_price 函数结束") # 使用 logging 记录函数结束

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
        logging.info(f"access_token: {access_token}")
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
    logging.info(f"send_wechat_message body: {body}")
    url = f'https://api.weixin.qq.com/cgi-bin/message/template/send?access_token={access_token}'
    try:
        response = requests.post(url, json=body)
        logging.info(f"send_wechat_message 响应: {response.text}")
        response.raise_for_status()  # 检查响应状态码
    except requests.exceptions.RequestException as e:
        logging.error(f"发送消息到微信失败: 网络请求错误: {e}")
        logging.error(f"send_wechat_message 失败 body: {body}")
    except Exception as e:
        logging.error(f"发送消息到微信失败: {e}")
        logging.error(f"send_wechat_message 失败 body: {body}")
    finally:
        logging.info("send_wechat_message 函数结束")

def eth_report():
    logging.info("eth_report 函数开始")
    access_token = get_access_token()
    if not access_token:
        logging.error("无法获取 access_token，停止发送消息")
        return

    logging.info(f"eth_report access_token: {access_token}")
    url = 'https://www.coingecko.com/zh/%E6%95%B0%E5%AD%97%E8%B4%A7%E5%B8%81/%E4%BB%A5%E5%A4%AA%E5%9D%8A'
    eth_price_str = fetch_eth_price(url)
    logging.info(f"获取到的原始价格字符串: {eth_price_str}")

    if eth_price_str:
        try:
            # 清理字符串，移除货币符号和千位分隔符，以便转换为浮点数
            # 例如: "$2,345.67" -> "2345.67"
            price_cleaned = ''.join(filter(lambda x: x in '0123456789.', eth_price_str))
            price_float = float(price_cleaned)
            logging.info(f"转换后的价格 (float): {price_float}")

            # 判断价格是否在预警范围内
            if price_float < 2100 or price_float > 2400:
                logging.info(f"价格 {price_float} 触发提醒条件 (< 2100 or > 2500)。准备发送提醒。")
                # 构造更详细的提醒消息
                message = f"当前价格: {eth_price_str}，已触发预警！"
                send_wechat_message(access_token, message)
            else:
                logging.info(f"当前价格 {price_float} 在正常范围内 (2100-2500)，不发送提醒。")

        except (ValueError, TypeError) as e:
            logging.error(f"无法将价格字符串 '{eth_price_str}' 转换为数字: {e}")
            # 如果转换失败，也发送一条通知，以便排查问题
            error_message = f"获取价格成功，但格式无法解析: {eth_price_str}"
            send_wechat_message(access_token, error_message)
    else:
        # 如果获取价格失败，发送失败通知
        send_wechat_message(access_token, "运行失败，未能获取以太坊价格")

    logging.info("eth_report 函数结束")

if __name__ == "__main__":
    logging.info("__main__ 开始")
    parser = argparse.ArgumentParser()
    parser.add_argument("--driver_path", help="Path to chromedriver")
    parser.add_argument("--chromium_path", help="Path to chrome")
    args = parser.parse_args()
    eth_report()
    logging.info("__main__ 结束")
