import argparse
import os
import uuid
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
# ... 其他代码 ...

def fetch_eth_price(url, driver_path=None, chromium_path=None):
    """
    使用 Selenium 获取动态渲染的页面 HTML 并提取以太坊价格.
    """
    try:
        chrome_options = Options()
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        #chrome_options.add_argument("--single-process") # 尝试移除
        #chrome_options.add_argument("--no-zygote") # 尝试移除
        user_data_dir = f"/tmp/chrome-user-data-{uuid.uuid4()}" # 添加随机字符串
        chrome_options.add_argument(f"--user-data-dir={user_data_dir}") # 添加
        chrome_options.add_argument("--remote-debugging-port=9223") # 尝试不同的端口

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
        print(f"ChromeOptions: {chrome_options.to_capabilities()}") # 打印 ChromeOptions

        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.get(url)
        try:
            # 等待价格元素出现并且可见
            WebDriverWait(driver, 30).until(
                EC.visibility_of_element_located((By.XPATH, '//div[@data-controller="coin-show" and contains(@class, "tw-relative")]//div[@class="tw-font-bold tw-text-gray-900 dark:tw-text-moon-50 tw-text-3xl md:tw-text-4xl tw-leading-10"]//span[@data-price-target="price"]'))
            )
        except Exception as e:
            print(f"等待价格元素加载失败: {e}")
            driver.quit()
            return None

        html = driver.page_source
        driver.quit()

        soup = BeautifulSoup(html, 'html.parser')
        price_element = soup.find('div', attrs={'data-controller': 'coin-show', 'class': lambda x: x and 'tw-relative' in x})
        if price_element:
            strong_element = price_element.find('div', attrs={'class': 'tw-font-bold tw-text-gray-900 dark:tw-text-moon-50 tw-text-3xl md:tw-text-4xl tw-leading-10'})
            if strong_element:
              price_span = strong_element.find('span', attrs={'data-price-target': 'price'})
              if price_span:
                price = price_span.text.strip()
                print(f"以太坊价格: {price}")
              else:
                print('未找到价格span')
                return None
            else:
                print('未找到价格 strong')
                return None
        else:
            print("获取价格失败")
            return None
        return price
    except Exception as e:
        print(f"获取页面信息失败: {e}")
        if 'driver' in locals():
            driver.quit()
        return None
    finally:
        try:
            driver.quit() # 确保 driver 关闭
        except:
            pass
