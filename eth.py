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
import platform

def fetch_eth_price(url, driver_path=None, chromium_path=None):
    """
    使用 Selenium 获取动态渲染的页面 HTML 并提取以太坊价格.
    """
    try:
        chrome_options = Options()
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--headless") # 移除 headless 模式
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
        if chromium_path:
          chrome_options.binary_location = chromium_path

        if driver_path:
            service = ChromeService(executable_path=driver_path)
        else:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            driver_path = os.path.join(current_dir, 'chromedriver.exe')
            if not os.path.exists(driver_path):
                print("chromedriver.exe not found in current directory.  Please specify --driver_path")
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
            driver.save_screenshot("error.png")
            print(driver.page_source) # 打印页面源代码
            driver.quit()
            return None

        html = driver.page_source
        driver.quit()
        
        soup = BeautifulSoup(html, 'html.parser')
        # 使用更精确的选择器直接找到价格 span
        price_span = soup.find('span', attrs={'data-converter-target': 'price', 'data-coin-id': '279', 'data-price-target': 'price'})

        if price_span:
            price = price_span.text.strip()
            print(f"以太坊价格: {price}")
        else:
            print("获取价格失败: 未找到价格 span")
            return None

        return price
    except Exception as e:
        print(f"获取页面信息失败: {e}")
        if 'driver' in locals():
            driver.quit()
        return None

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--driver_path", help="Path to chromedriver")
    parser.add_argument("--chromium_path", help="Path to chrome")
    args = parser.parse_args()

    url = 'https://www.coingecko.com/zh/%E6%95%B0%E5%AD%97%E8%B4%A7%E5%B8%81/%E4%BB%A5%E5%A4%AA%E5%9D%8A'

    eth_price = fetch_eth_price(url, driver_path=args.driver_path, chromium_path=args.chromium_path)
