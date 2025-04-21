import json
import os
from playwright.sync_api import sync_playwright, Playwright, expect
import time
from decimal import Decimal, InvalidOperation
import datetime
import lark_oapi as lark
from lark_oapi.api.bitable.v1 import *

# --- 配置 ---
COOKIE_FILE = 'laike.json'
TARGET_URL = 'https://www.life-data.cn/?groupid=1768205901316096&channel_id=laike_data_first_menu'
DATA_CONTAINER_SELECTOR = "#tradeMeasure"

# --- 飞书配置 ---
FEISHU_APP_ID = "cli_a6672cae343ad00e"
FEISHU_APP_SECRET = "0J4SpfBMeIxJEOXDJMNbofMipRgwkMpV"
BASE_APP_TOKEN = "NpQdbpdTjaPJRgsgRLwc9rqpnhd"
TABLE_ID = "tblErvGwP0fokZxz"

# --- !!! 关键：确认这三个列名在你的飞书表格中是正确的 !!! ---
FEISHU_FIELD_PROJECT = "项目"     # <-- 你的“项目”列名
FEISHU_FIELD_AMOUNT = "金额"      # <-- 你的“金额”列名
FEISHU_FIELD_PERIOD = "时间周期" # <-- 替换成你表格中表示“时间周期”的列名

# --- Playwright 获取数据的函数 (不变) ---
def get_data_from_web(playwright: Playwright) -> dict | None:
    """使用 Playwright 访问网页并提取所需数据"""
    if not os.path.exists(COOKIE_FILE):
        print(f"错误：找不到 Cookie 文件 '{COOKIE_FILE}'。")
        return None
    try:
        with open(COOKIE_FILE, 'r', encoding='utf-8') as f:
            cookies_raw = json.load(f)
        print(f"成功从 '{COOKIE_FILE}' 加载了 {len(cookies_raw)} 个原始 Cookie。")
    except Exception as e:
        print(f"读取或解析 Cookie 文件时出错: {e}")
        return None
    corrected_cookies = []
    valid_same_site_values = {"Strict", "Lax", "None"}
    for cookie in cookies_raw:
        if not isinstance(cookie, dict): continue
        original_same_site = cookie.get('sameSite')
        secure = cookie.get('secure', False)
        if original_same_site is None: cookie['sameSite'] = 'None' if secure else 'Lax'
        elif isinstance(original_same_site, str):
            lower_same_site = original_same_site.lower()
            if lower_same_site == 'no_restriction': cookie['sameSite'] = 'None'
            elif lower_same_site == 'lax': cookie['sameSite'] = 'Lax'
            elif lower_same_site == 'strict': cookie['sameSite'] = 'Strict'
            elif lower_same_site == 'none': cookie['sameSite'] = 'None'
            else: cookie['sameSite'] = 'None' if secure else 'Lax'
        else: cookie['sameSite'] = 'None' if secure else 'Lax'
        if 'name' not in cookie or 'value' not in cookie: continue
        if 'expirationDate' in cookie:
            if isinstance(cookie['expirationDate'], (int, float)): cookie['expires'] = int(cookie['expirationDate'])
            del cookie['expirationDate']
        cookie.pop('storeId', None)
        corrected_cookies.append(cookie)
    browser = None
    context = None
    extracted_data = {}
    try:
        browser = playwright.chromium.launch(headless=True, slow_mo=50)
        context = browser.new_context()
        if corrected_cookies: context.add_cookies(corrected_cookies)
        else: print("没有有效的 Cookie 可供添加。")
        page = context.new_page()
        viewport_height = 1600
        viewport_width = 1920
        print(f"设置浏览器视口大小为: {viewport_width}x{viewport_height}")
        page.set_viewport_size({"width": viewport_width, "height": viewport_height})
        print(f"正在导航到目标网址: {TARGET_URL}")
        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
        print("DOM 加载完成，等待页面内容加载...")
        print("页面基础加载完成，等待 5 秒让动态内容加载...")
        page.wait_for_timeout(5000)
        print("\n--- 开始提取数据 ---")
        base_card_selector = f"{DATA_CONTAINER_SELECTOR} .dd-measure-card"
        value_selector_suffix = ".dd-measure-value-primary-content span.dd-measure-value"
        store_count_selector = 'span:has-text("门店数") > span[style*="font-weight: 500"]'
        items_to_extract = {
            "成交金额": f"{base_card_selector} >> nth=0 >> {value_selector_suffix}",
            "核销金额": f"{base_card_selector} >> nth=2 >> {value_selector_suffix}",
            "门店数": store_count_selector
        }
        for name, selector in items_to_extract.items():
            print(f"\n尝试获取 {name} (选择器: {selector})")
            try:
                element = page.locator(selector)
                print(f"  - 等待元素可见...")
                expect(element).to_be_visible(timeout=15000)
                print(f"  - 元素已可见, 等待元素非空...")
                expect(element).not_to_be_empty(timeout=5000)
                print(f"  - 元素检查通过.")
                value_str = element.text_content()
                print(f"  - 原始文本: '{value_str.strip()}'")
                cleaned_str = value_str.strip().replace('¥', '').replace(',', '')
                try:
                    extracted_data[name] = Decimal(cleaned_str)
                    print(f"成功获取并处理 {name}: {extracted_data[name]}")
                except InvalidOperation:
                    print(f"!!! 处理 {name} 时出错：无法将 '{cleaned_str}' 转换为数字。")
                    extracted_data[name] = None
            except Exception as e:
                error_screenshot_path = f"screenshot_error_{name.replace(' ', '_')}.png"
                try: page.screenshot(path=error_screenshot_path)
                except Exception as se: print(f"!!! 获取 {name} 时出错，且保存截图失败: {se}。原始错误: {e}")
                extracted_data[name] = None
        print("--- 数据提取完成 ---")
        return extracted_data
    except Exception as e:
        print(f"Playwright 操作过程中发生错误: {e}")
        if 'page' in locals() and page:
             try: page.screenshot(path='screenshot_playwright_error.png')
             except Exception as se: print(f"保存错误截图失败: {se}")
        return None
    finally:
        if context: context.close()
        if browser: browser.close()
        print("浏览器已关闭。")

# --- 飞书写入函数 (加入时间周期) ---
def write_to_feishu(data: dict):
    """将提取的 GMV、核销、门店数 及时间周期 分别作为三行写入飞书"""
    if not data or "成交金额" not in data or "核销金额" not in data or "门店数" not in data:
        print("错误：提供给飞书的数据不完整或无效。")
        return

    gmv_value = data.get("成交金额")
    hx_value = data.get("核销金额")
    store_count_value = data.get("门店数")

    # 检查数据是否有效
    if not isinstance(gmv_value, Decimal) or \
       not isinstance(hx_value, Decimal) or \
       not isinstance(store_count_value, Decimal):
        print("错误：成交金额、核销金额或门店数数据无效，无法写入飞书。")
        return

    # --- 计算时间周期 ---
    try:
        beijing_tz = datetime.timezone(datetime.timedelta(hours=8))
        # 直接获取北京时间，避免 UTC 转换复杂性
        today_beijing = datetime.datetime.now(beijing_tz).date()
        yesterday = today_beijing - datetime.timedelta(days=1)
        start_date = today_beijing - datetime.timedelta(days=7) # 今天往前数7天，即前7天的开始日期
        # 格式化为 "M.D~M.D"
        period_str = f"{start_date.month}.{start_date.day}~{yesterday.month}.{yesterday.day}"
        print(f"计算得到的时间周期: {period_str}")
    except Exception as e:
        print(f"计算时间周期时出错: {e}")
        period_str = "计算错误" # 出错时给个默认值

    # --- 创建飞书 Client ---
    client = lark.Client.builder() \
        .app_id(FEISHU_APP_ID) \
        .app_secret(FEISHU_APP_SECRET) \
        .log_level(lark.LogLevel.INFO) \
        .build()

    # --- 构造三条记录 ---
    records_to_create = []

    # 记录 1: GMV
    fields_gmv = {
        FEISHU_FIELD_PROJECT: "GMV",
        FEISHU_FIELD_AMOUNT: float(gmv_value),
        FEISHU_FIELD_PERIOD: period_str # <-- 加入时间周期
        # 如果有日期字段: FEISHU_FIELD_DATE: int(time.time() * 1000)
    }
    records_to_create.append(AppTableRecord.builder().fields(fields_gmv).build())
    print(f"准备写入飞书的第1条记录: {fields_gmv}")

    # 记录 2: 核销
    fields_hx = {
        FEISHU_FIELD_PROJECT: "核销",
        FEISHU_FIELD_AMOUNT: float(hx_value),
        FEISHU_FIELD_PERIOD: period_str # <-- 加入时间周期
        # 如果有日期字段: FEISHU_FIELD_DATE: int(time.time() * 1000)
    }
    records_to_create.append(AppTableRecord.builder().fields(fields_hx).build())
    print(f"准备写入飞书的第2条记录: {fields_hx}")

    # 记录 3: 门店数量
    fields_store = {
        FEISHU_FIELD_PROJECT: "门店数量", # 或者叫 "门店数"
        FEISHU_FIELD_AMOUNT: int(store_count_value),
        FEISHU_FIELD_PERIOD: period_str # <-- 加入时间周期
        # 如果有日期字段: FEISHU_FIELD_DATE: int(time.time() * 1000)
    }
    records_to_create.append(AppTableRecord.builder().fields(fields_store).build())
    print(f"准备写入飞书的第3条记录: {fields_store}")

    # --- 构造请求体 ---
    request_body = BatchCreateAppTableRecordRequestBody.builder() \
        .records(records_to_create) \
        .build()

    request: BatchCreateAppTableRecordRequest = BatchCreateAppTableRecordRequest.builder() \
        .app_token(BASE_APP_TOKEN) \
        .table_id(TABLE_ID) \
        .request_body(request_body) \
        .build()

    # --- 发起请求 ---
    try:
        response: BatchCreateAppTableRecordResponse = client.bitable.v1.app_table_record.batch_create(request)

        # --- 处理响应 ---
        if not response.success():
            lark.logger.error(
                f"飞书 API 请求失败, code: {response.code}, msg: {response.msg}, log_id: {response.get_log_id()}")
            try:
                raw_content = json.loads(response.raw.content)
                lark.logger.error(f"响应详情: \n{json.dumps(raw_content, indent=4, ensure_ascii=False)}")
            except:
                 lark.logger.error(f"原始响应内容: {response.raw.content.decode('utf-8')}")
            return

        print(f"成功写入 {len(records_to_create)} 条记录到飞书多维表格！")
        lark.logger.info(lark.JSON.marshal(response.data, indent=4))

    except Exception as e:
        print(f"调用飞书 API 时发生异常: {e}")


# --- 主执行逻辑 ---
if __name__ == "__main__":
    print("开始执行脚本...")
    web_data = None
    with sync_playwright() as playwright:
        web_data = get_data_from_web(playwright)

    if web_data:
        print("\n从网页获取到的数据:")
        print(f"- 成交金额: {web_data.get('成交金额', '提取失败')}")
        print(f"- 核销金额: {web_data.get('核销金额', '提取失败')}")
        print(f"- 门店数: {web_data.get('门店数', '提取失败')}")

        print("\n开始写入飞书多维表格...")
        write_to_feishu(web_data) # 调用写入函数
    else:
        print("\n未能从网页获取数据，无法写入飞书。")

    print("\n脚本执行完毕。")
