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

def is_hardware_related(titles, api_key):
    """
    使用大语言模型判断新闻标题是否与电脑硬件及游戏相关，只返回相关内容。
    接收一个新闻标题列表，并返回过滤后的列表
    """
    url = "https://api.siliconflow.cn/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    # 构建 AI Prompt，包括所有的输入和输出示例
    example_prompt = """请分析以下新闻标题列表，提取出与电脑硬件（例如 CPU、GPU、主板、内存、硬盘、显示器等）和电子游戏（包括游戏发布、游戏更新、游戏硬件评测等）直接相关的新闻标题。如果新闻标题与这两个主题无关，请不要输出任何内容。请只返回相关新闻的标题，并且每行一个标题。

例如：
输入：
终结命名混乱，USB 全新徽标直接标注传输速度、功率瓦数
华为余承东 2025 全员信：鸿蒙三分天下有其一，10 万个原生应用是未来半年到一年关键目标
王守义十三香给 1000 多名员工发华为 Mate 60：迎来 40 周年厂庆
华为余承东晒自购享界 S9：感觉非常棒，百公里电耗 11.4kWh
彻底脱去伪装，鸿蒙智行问界 M8 大量实车谍照曝光
雷军亲赴黑河冬测：不只有“泼水成冰”，还验收小米 SU7 Ultra / YU7 成果
尾号 0000000 的手机号拍卖：70 万成交，只有使用权没有所有权
26.35 万元起，特斯拉焕新 Model Y 冰河蓝实车曝光
冯骥回应《黑神话：悟空》更新 Steam 上线最晚：先在人少平台灰度测试
泰国推出旅游警察 App：可发送定位、报警
三只羊旗下“小杨甄选”转战微信视频号平台复播
零跑汽车成第二家盈利新势力，提前一年达成目标
输出：
终结命名混乱，USB 全新徽标直接标注传输速度、功率瓦数
冯骥回应《黑神话：悟空》更新 Steam 上线最晚：先在人少平台灰度测试

现在请分析以下新闻标题列表:\n""" + "\n".join(titles)

    payload = {
        "model": "Qwen/Qwen2.5-7B-Instruct",
        "messages": [
            {
                "role": "user",
                "content": example_prompt
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
            # 将 AI 返回的文本按行拆分，并去除空行，生成结果列表
            filtered_titles = [line for line in content.splitlines() if line]
            return filtered_titles
        return []
    except requests.exceptions.RequestException as e:
        print(f"AI 过滤请求失败: {e}")
        return []


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--driver_path", help="Path to chromedriver")
    parser.add_argument("--chromium_path", help="Path to chrome")
    args = parser.parse_args()

    urls = [
        'https://rebang.today/tech?tab=ifanr',
        'https://rebang.today/tech?tab=landian',
        'https://rebang.today/tech?tab=36kr'
    ]
    
    all_hardware_news = []

    api_key = os.getenv("SILICONFLOW_API_KEY")
    if not api_key:
        print("请设置环境变量 'SILICONFLOW_API_KEY'")
        exit()

    for url in urls:
        html = fetch_hot_news(url, driver_path=args.driver_path, chromium_path = args.chromium_path)
        if html:
            news_list = parse_html(html)
            if news_list:
                titles = [item['title'] for item in news_list]
                filtered_titles = is_hardware_related(titles, api_key)
                
                hardware_news = []
                for item in news_list:
                    if item['title'] in filtered_titles:
                         hardware_news.append(item)
                all_hardware_news.extend(hardware_news)
        else:
             print(f"获取 {url} 页面信息失败")
    if all_hardware_news:
        content = "今日电脑硬件及游戏热点:\n"
        for item in all_hardware_news:
            content += f"- {item['title']}: {item['link']}\n"
         # 发送企业微信
        success = send_to_wechat_bot(content)
        if success:
            print("消息发送成功")
        else:
           print("消息发送失败")
    else:
        print("没有找到相关的电脑硬件及游戏新闻")
