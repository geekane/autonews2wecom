import argparse
import os
import uuid
import platform
import requests
import json
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import io
import sys

# 定义全局变量
program_log = io.StringIO(encoding="utf-8")  # 添加编码
sys.stdout = program_log

print("标准输出已重定向")  # 添加

# 从测试号信息获取
appID = os.getenv("APPID")  # 从环境变量中获取
appSecret = os.getenv("APPSECRET")  # 从环境变量中获取
# 收信人ID即 用户列表中的微信号，见上文
openId = os.getenv("OPENID")  # 从环境变量中获取
# ETH模板ID
eth_template_id = os.getenv("ETH_TEMPLATE_ID")  # 从环境变量中获取

if not appID or not appSecret or not openId or not eth_template_id:
    print("缺少环境变量：请检查 APPID, APPSECRET, OPENID 和 ETH_TEMPLATE_ID 是否已正确设置")
    exit()

def fetch_eth_price(url, driver_path=None, chromium_path=None):
    """
    使用 Selenium 获取动态渲染的页面 HTML 并提取以太坊价格.
    """
    print("fetch_eth_price 函数开始")
    try:
        chrome_options = Options()
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--headless") # 添加 headless 模式
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
        if chromium_path:
          chrome_options.binary_location = chromium_path

        if driver_path:
            service = ChromeService(executable_path=driver_path)
        else:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            driver_path = os.path.join(current_dir, 'chromedriver')
            if not os.path.exists(driver_path):
                print("chromedriver not found in current directory.")
                return None
            service = ChromeService(executable_path=driver_path)

        print(f"Using chromedriver at: {driver_path}") # 打印正在使用的chromedriver路径
        print(f"Python architecture: {platform.architecture()}") # 打印Python架构

        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.get(url)
        try:
            # 等待价格元素出现
            element = WebDriverWait(driver, 60).until(
                EC.presence_of_element_located((By.XPATH, '//span[@data-converter-target="price" and @data-coin-id="279" and @data-price-target="price"]'))
            )

            if not element.is_displayed():
                print("元素存在，但不可见")
                print(f"CSS display 属性: {element.value_of_css_property('display')}")
                print(f"CSS visibility 属性: {element.value_of_css_property('visibility')}")

        except Exception as e:
            print(f"等待价格元素加载失败: {e}")
            try:
                driver.save_screenshot("error.png") # 尝试截图
            except:
                pass
            try:
                print(driver.page_source) # 尝试打印页面源代码
            except:
                pass
            try:
                driver.quit()
            except:
                pass
            return None

        html = driver.page_source
        try:
            driver.quit()
        except:
            pass
        
        soup = BeautifulSoup(html, 'html.parser')
        # 使用更精确的选择器直接找到价格 span
        price_span = soup.find('span', attrs={'data-converter-target': 'price', 'data-coin-id': '279', 'data-price-target': 'price'})

        if price_span:
            price = price_span.text.strip()
            print(f"以太坊价格: {price}")
            print("fetch_eth_price 函数结束，成功")
            return price
        else:
            print("获取价格失败: 未找到价格 span")
            return None

    except Exception as e:
        print(f"获取页面信息失败: {e}")
        return None
    finally:
        try:
            driver.quit()
        except:
            pass
        print("fetch_eth_price 函数结束")

def get_access_token():
    print("get_access_token 函数开始")
    # 获取access token的url
    url = 'https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={}&secret={}' \
        .format(appID.strip(), appSecret.strip())
    response = requests.get(url).json()
    print(f"get_access_token 响应: {response}")
    access_token = response.get('access_token')
    print(f"access_token: {access_token}")
    print("get_access_token 函数结束")
    return access_token


def send_wechat_message(access_token, message):
    print("send_wechat_message 函数开始")
    # touser 就是 openID
    # template_id 就是模板ID
    # url 就是点击模板跳转的url
    # data就按这种格式写，time和text就是之前{{time.DATA}}中的那个time，value就是你要替换DATA的值

    body = {
        "touser": openId.strip(),
        "template_id": eth_template_id.strip(),
        "url": "https://weixin.qq.com",
        "data": {
            "ETH": {  # 修改为 ETH
                "value": message  # 将所有日志内容放在这里
            },
        }
    }
    print(f"send_wechat_message body: {body}")
    url = 'https://api.weixin.qq.com/cgi-bin/message/template/send?access_token={}'.format(access_token)
    response = requests.post(url, json.dumps(body))
    print(f"send_wechat_message 响应: {response.text}")
    print("send_wechat_message 函数结束")


def eth_report():
    print("eth_report 函数开始")
    # 1.获取access_token
    access_token = get_access_token()
    print(f"eth_report access_token: {access_token}")
    # 2. 获取以太坊价格
    url = 'https://www.coingecko.com/zh/%E6%95%B0%E5%AD%97%E8%B4%A7%E5%B8%81/%E4%BB%A5%E5%A4%AA%E5%9D%8A'
    eth_price = fetch_eth_price(url)
    print(f"eth_report eth_price: {eth_price}")
    # 3. 发送消息
    send_wechat_message(access_token, program_log.getvalue())  # 发送整个日志
    print("eth_report 函数结束")

if __name__ == "__main__":
    print("__main__ 开始")
    # 捕获所有输出
    program_log = io.StringIO(encoding="utf-8")  # 添加编码
    sys.stdout = program_log

    try:  # 添加 try...finally 块
        parser = argparse.ArgumentParser()
        parser.add_argument("--driver_path", help="Path to chromedriver")
        parser.add_argument("--chromium_path", help="Path to chrome")
        args = parser.parse_args()

        eth_report()
    finally:  # 确保恢复标准输出
        # 恢复标准输出
        sys.stdout = sys.__stdout__
        print("__main__ 结束")
