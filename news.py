from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import os
import requests
import json
import argparse


def fetch_hot_news(url, driver_path=None, chromium_path=None):
    """
    使用 Selenium 获取动态渲染的页面 HTML (Edge 浏览器).

    Args:
        url (str): 目标 URL.
        driver_path (str, optional): WebDriver 的路径. 如果 WebDriver 在系统路径中则不需要提供.
        chromium_path (str, optional): Chromium 可执行文件的路径.

    Returns:
        str: 页面 HTML 或 None (如果获取失败).
    """
    try:
        chrome_options = Options()
        chrome_options.add_argument("--headless")  # 无头模式
        chrome_options.add_argument("--no-sandbox")  # 禁用沙箱模式
        chrome_options.add_argument("--disable-dev-shm-usage")  # 禁用内存共享
        if chromium_path:
          chrome_options.binary_location = chromium_path

        if driver_path:
             service = ChromeService(executable_path=driver_path)
        else:
            # 尝试在当前目录下查找 chromedriver
            current_dir = os.path.dirname(os.path.abspath(__file__))
            driver_path = os.path.join(current_dir, 'chromedriver')
            if os.path.exists(driver_path):
               service = ChromeService(executable_path=driver_path)
            else:
                service = ChromeService()

        driver = webdriver.Chrome(service=service, options=chrome_options)


        driver.get(url)

        # 等待页面加载完成，可以根据实际情况调整
        # 等待页面列表元素加载完成
        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, "a.no-underline"))
            )
        except Exception as e:
            print(f"等待元素加载失败: {e}")
            driver.quit()
            return None

        html = driver.page_source
        driver.quit()  # 关闭浏览器
        return html
    except Exception as e:
        print(f"获取页面信息失败: {e}")
        if 'driver' in locals():
            driver.quit()
        return None


def parse_html(html):
    soup = BeautifulSoup(html, 'html.parser')
    # 根据实际情况查找热点信息，这部分需要您根据实际的HTML结构进行调整
    hot_news_items = soup.select('a.no-underline')  # 查找所有具有 no-underline 类的 a 标签
    hot_news = []
    for item in hot_news_items:
        title_element = item.find('h2', class_='text-base')  # 查找 h2标签，class=text-base
        if title_element:
            title = title_element.get_text(strip=True)  # 获取标题文本
            link = item['href']  # 获取链接
            hot_news.append({'title': title, 'link': link})  # 添加到热点列表
    return hot_news


def send_to_wechat_bot(content):
    """
    发送消息到企业微信机器人
    """
    webhook_key = os.getenv('WECOM_WEBHOOK_KEY')  # 从环境变量中获取 key
    webhook_url = f'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={webhook_key}'
    data = {
        "msgtype": "text",
        "text": {
            "content": content
        }
    }
    try:
        response = requests.post(webhook_url, json=data)
        response.raise_for_status()  # 如果响应状态码不是200，抛出异常
        return response.status_code == 200
    except requests.exceptions.RequestException as e:
        print(f"发送消息到企业微信机器人失败: {e}")
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--driver_path", help="Path to chromedriver")
    parser.add_argument("--chromium_path", help="Path to chrome")
    args = parser.parse_args()

    url = 'https://rebang.today/tech?tab=ithome'
    # 请根据实际情况修改driver路径，如果driver在系统路径中，可以不传
    html = fetch_hot_news(url, driver_path=args.driver_path, chromium_path = args.chromium_path)
    if html:
        news_list = parse_html(html)
        if news_list:
            # 格式化成文本
            content = "今日热点:\n"
            for item in news_list:
                content += f"- <{item['link']}|{item['title']}>\n"
            # 发送企业微信
            success = send_to_wechat_bot(content)
            if success:
                print("消息发送成功")
            else:
                print("消息发送失败")
        else:
            print('没有找到热点信息')
    else:
        print('获取页面信息失败')
