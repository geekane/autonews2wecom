import argparse
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

def fetch_hot_news(url, driver_path=None, chromium_path=None):
    """
    使用 Selenium 获取动态渲染的页面 HTML.
    """
    try:
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        if chromium_path:
          chrome_options.binary_location = chromium_path

        if driver_path:
            service = ChromeService(executable_path=driver_path)
        else:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            driver_path = os.path.join(current_dir, 'chromedriver')
            if os.path.exists(driver_path):
               service = ChromeService(executable_path=driver_path)
            else:
                service = ChromeService()

        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.get(url)
        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, "a.no-underline"))
            )
        except Exception as e:
            print(f"等待元素加载失败: {e}")
            driver.quit()
            return None

        html = driver.page_source
        driver.quit()
        return html
    except Exception as e:
        print(f"获取页面信息失败: {e}")
        if 'driver' in locals():
            driver.quit()
        return None


def parse_html(html):
    soup = BeautifulSoup(html, 'html.parser')
    hot_news_items = soup.select('a.no-underline')
    hot_news = []
    for item in hot_news_items:
        title_element = item.find('h2', class_='text-base')
        if title_element:
            title = title_element.get_text(strip=True)
            link = item['href']
            hot_news.append({'title': title, 'link': link})
    return hot_news


def send_to_wechat_bot(content):
    """
    发送消息到企业微信机器人.
    """
    webhook_key = os.getenv('WECOM_WEBHOOK_KEY')
    webhook_url = f'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={webhook_key}'
    data = {
        "msgtype": "text",
        "text": {
            "content": content
        }
    }
    try:
        response = requests.post(webhook_url, json=data)
        response.raise_for_status()
        return response.status_code == 200
    except requests.exceptions.RequestException as e:
        print(f"发送消息到企业微信机器人失败: {e}")
        return False

def is_hardware_related(title, api_key):
    """
    使用大语言模型判断新闻标题是否与电脑硬件及游戏相关，只返回相关内容。
    """
    url = "https://api.siliconflow.cn/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "Qwen/Qwen2.5-7B-Instruct",
         "messages": [
            {
                "role": "user",
                "content": f"根据以下信息：{title}。提取出和电脑硬件以及游戏相关的新闻，其他不用给"
                """
    使用大语言模型判断新闻标题是否与电脑硬件及游戏相关，只返回相关内容。

    参数:
    title (str): 新闻标题
    api_key (str): API 密钥

    返回:
    str: 如果新闻标题与电脑硬件及游戏相关，返回相关内容；否则返回 None
    """
    url = "https://api.siliconflow.cn/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "Qwen/Qwen2.5-7B-Instruct",
        "messages": [
            {
                "role": "user",
                "content": f"请分析以下新闻标题：{title}，提取出与电脑硬件（例如 CPU、GPU、主板、内存、硬盘、显示器等）和电子游戏（包括游戏发布、游戏更新、游戏硬件评测等）直接相关的新闻标题。如果新闻标题与这两个主题无关，请不要输出任何内容。请只返回相关新闻的标题，不要包含任何其他解释或说明。"
            }
        ],
        "stream": False,
        "max_tokens": 512,
        "temperature": 0.1,
    }
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        if data and data.get("choices") and data["choices"][0].get("message"):
            content = data["choices"][0]["message"].get("content", "").strip()
            # 判断content是否为空，如果为空则表示不相关
            return content if content else None
        return None
    except requests.exceptions.RequestException as e:
        print(f"AI 过滤请求失败: {e}")
        return None
        
            }
        ],
        "stream": False,
        "max_tokens": 512,
        "temperature": 0.1,
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        if data and data.get("choices") and data["choices"][0].get("message"):
            content = data["choices"][0]["message"].get("content", "").strip()
            # 判断content是否为空，如果为空则表示不相关
            return content if content else None 
        return None # 如果请求失败或者没有返回content，则返回None
    except requests.exceptions.RequestException as e:
        print(f"AI 过滤请求失败: {e}")
        return None

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--driver_path", help="Path to chromedriver")
    parser.add_argument("--chromium_path", help="Path to chrome")
    args = parser.parse_args()

    url = 'https://rebang.today/tech?tab=ithome'
    html = fetch_hot_news(url, driver_path=args.driver_path, chromium_path = args.chromium_path)
    if html:
        news_list = parse_html(html)
        if news_list:
             # 过滤硬件相关新闻
            api_key = os.getenv("SILICONFLOW_API_KEY")
            if not api_key:
                print("请设置环境变量 'SILICONFLOW_API_KEY'")
                exit()
            hardware_news = []
            for item in news_list:
                 ai_response = is_hardware_related(item['title'], api_key)
                 if ai_response:
                     hardware_news.append({'title': ai_response, 'link': item['link']})
            if hardware_news:
                content = "今日电脑硬件及游戏热点:\n"
                for item in hardware_news:
                    content += f"- {item['title']}: {item['link']}\n"
                # 发送企业微信
                success = send_to_wechat_bot(content)
                if success:
                    print("消息发送成功")
                else:
                    print("消息发送失败")
            else:
                print("没有找到相关的电脑硬件及游戏新闻")
        else:
            print('没有找到热点信息')
    else:
        print('获取页面信息失败')
