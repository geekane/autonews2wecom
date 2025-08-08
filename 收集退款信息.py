import json
import asyncio
import os
import pandas as pd
from playwright.async_api import async_playwright, Page, TimeoutError

# 导入飞书SDK
import lark_oapi as lark
from lark_oapi.api.bitable.v1 import *

# --- 基础配置 ---
COOKIE_FILE = '来客.json'
BASE_URL = 'https://life.douyin.com/p/liteapp/fulfillment-fusion/refund?groupid=1768205901316096'
EXPORT_FILE_NAME = "退款记录.xlsx"
ERROR_SCREENSHOT_FILE = "error_screenshot.png"

# --- 飞书多维表格 API 配置 ---
FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID")
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET")
FEISHU_APP_TOKEN = "MslRbdwPca7P6qsqbqgcvpBGnRh"
FEISHU_TABLE_ID = "tbljY9UiV7m5yk67"

# =========================================================
# 新增: 用于处理各类弹窗的函数
# =========================================================
async def close_potential_popups(page: Page):
    """
    检查并关闭潜在的引导/升级弹窗。
    """
    print("\n步骤: 检查并关闭潜在的引导/升级弹窗...")
    try:
        # 策略: 寻找并点击 "功能升级啦" 弹窗的关闭按钮 'x'
        # 这个选择器是根据常见弹窗结构推断的，如果无效，需要用Inspector精确定位
        # div[role='dialog'] 表示弹窗本身, button[aria-label='Close'] 是常见的关闭按钮
        close_button = page.locator("div[role='dialog'] button[aria-label='Close'], div.semi-modal-close")
        
        # 使用5秒的短超时来检查
        if await close_button.is_visible(timeout=5000):
            print("检测到 '功能升级' 弹窗，正在点击关闭按钮...")
            await close_button.first.click()
            await page.wait_for_timeout(1000)
            print("弹窗已关闭。")
            return

    except TimeoutError:
        print("✅ 在检查时间内未发现已知的弹窗。")
    except Exception as e:
        print(f"关闭弹窗时发生未知错误: {e}")

async def write_df_to_feishu_bitable(df: pd.DataFrame):
    # 此函数内容无需修改，保持原样
    print("\n--- 开始将数据【批量写入】飞书多维表格 ---")
    if not FEISHU_APP_ID or not FEISHU_APP_SECRET:
        print("❌ 错误：飞书的 App ID 或 App Secret 环境变量未设置！")
        return
    client = lark.Client.builder().app_id(FEISHU_APP_ID).app_secret(FEISHU_APP_SECRET).log_level(lark.LogLevel.INFO).build()
    total_rows = len(df)
    if total_rows == 0:
        print("没有需要写入的数据。")
        return
    print("正在准备所有待上传的记录...")
    records_to_create = []
    for index, row in df.iterrows():
        fields_data = {}
        for col_name, value in row.items():
            if pd.isna(value):
                fields_data[col_name] = ""
            elif col_name == '退款申请时间':
                timestamp_ms = int(value.timestamp() * 1000)
                fields_data[col_name] = timestamp_ms
            else:
                fields_data[col_name] = str(value)
        record = AppTableRecord.builder().fields(fields_data).build()
        records_to_create.append(record)
    batch_size = 500
    success_count = 0
    for i in range(0, total_rows, batch_size):
        chunk = records_to_create[i:i + batch_size]
        print(f"正在处理第 {i + 1} 到 {i + len(chunk)} 条记录的批次...")
        try:
            request_body = BatchCreateAppTableRecordRequestBody.builder().records(chunk).build()
            request: BatchCreateAppTableRecordRequest = BatchCreateAppTableRecordRequest.builder().app_token(FEISHU_APP_TOKEN).table_id(FEISHU_TABLE_ID).request_body(request_body).build()
            response: BatchCreateAppTableRecordResponse = client.bitable.v1.app_table_record.batch_create(request)
            if not response.success():
                lark.logger.error(f"❌ 批次写入失败, code: {response.code}, msg: {response.msg}, log_id: {response.get_log_id()}")
            else:
                num_succeeded_in_batch = len(response.data.records)
                success_count += num_succeeded_in_batch
                lark.logger.info(f"✅ 批次写入成功，新增 {num_succeeded_in_batch} 条记录。")
        except Exception as e:
            print(f"❌ 在处理批次时发生SDK或网络异常: {e}")
    print(f"--- 飞书多维表格批量写入完成 ---")
    print(f"总计 {total_rows} 条记录，成功写入 {success_count} 条。")

async def export_and_process_data(page: Page):
    # 此函数内容无需修改，保持原样
    print("\n--- 开始执行数据导出、处理与上传流程 ---")
    try:
        print("步骤 1: 点击导出菜单的触发图标...")
        await page.locator(".byted-content-inner-wrapper > .byted-icon > svg > g > path").click(timeout=15000)
        await page.wait_for_timeout(1000)
        print("步骤 2: 点击 '待处理' 选项卡...")
        await page.locator('.byted-radio-tag:has-text("待处理")').click()
        await page.wait_for_timeout(3000)
        print("'待处理' 列表加载完成。")
        await page.wait_for_timeout(5000)
        print("步骤 3: 点击 '导出数据' 按钮...")
        await page.get_by_role("button", name="导出数据").click()
        await page.wait_for_timeout(1000)
        print("步骤 4: 点击 '确定导出'，并捕获新页面...")
        async with page.context.expect_page() as new_page_info:
            # 已修正笔误： "确定导出导出" -> "确定导出"
            await page.get_by_role("button", name="确定导出").click()
        new_page = await new_page_info.value

        print("新页面已捕获，正在等待 '下载' 按钮加载...")
        download_button_selector = new_page.get_by_text("下载").nth(3)
        await download_button_selector.wait_for(state="visible", timeout=60000)
        print("✅ '下载' 按钮已可见。")

        print("步骤 5: 在新页面上点击 '下载' 按钮...")
        async with new_page.expect_download() as download_info:
            await download_button_selector.click()
        download = await download_info.value

        if os.path.exists(EXPORT_FILE_NAME):
            os.remove(EXPORT_FILE_NAME)
        await download.save_as(EXPORT_FILE_NAME)
        print(f"✅ 文件已成功下载: {EXPORT_FILE_NAME}")
        await new_page.close()

        print("\n步骤 6: 读取并筛选Excel数据...")
        if not os.path.exists(EXPORT_FILE_NAME):
            print(f"❌ 错误：找不到下载的文件 {EXPORT_FILE_NAME}")
            return False
        df = pd.read_excel(EXPORT_FILE_NAME)
        if df.empty:
            print("✅ 下载的Excel文件为空，没有需要处理的数据。")
            return True
        required_columns = ['核销门店', '商品名称', '退款申请时间', '退款申请原因', '订单实收(元)', '退款金额(元)']
        for col in required_columns:
            if col not in df.columns:
                print(f"❌ 错误: 下载的Excel文件中缺少必需的列: '{col}'")
                return False
        filtered_df = df[required_columns].copy()
        filtered_df['退款申请时间'] = pd.to_datetime(filtered_df['退款申请时间'])
        print("✅ 数据筛选完成。预览筛选后的数据 (前5行):")
        print(filtered_df.head().to_string())
        await write_df_to_feishu_bitable(filtered_df)
        print("--- 数据导出、处理与上传流程执行成功 ---\n")
        return True
    except Exception as e:
        print(f"❌ 在执行导出、处理与上传流程时发生错误: {e}")
        return False

async def main():
    """
    主执行函数，包含浏览器初始化、错误捕获和截图逻辑。
    """
    async with async_playwright() as p:
        print(f"正在从 {COOKIE_FILE} 文件中读取 cookie...")
        try:
            with open(COOKIE_FILE, 'r', encoding='utf-8') as f:
                cookies = json.load(f).get('cookies', [])
        except FileNotFoundError:
            print(f"❌ 致命错误：找不到 Cookie 文件 '{COOKIE_FILE}'。")
            exit(1)
        except Exception as e:
            print(f"❌ 致命错误: 无法读取或解析Cookie文件: {e}")
            exit(1)

        print("正在启动 Chromium 浏览器...")
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            print("正在添加 Cookie 到浏览器上下文...")
            await context.add_cookies(cookies)
            
            print("正在导航至基础页面...")
            # =========================================================
            # 已修改: 使用更宽松的等待条件，并优雅处理超时
            # =========================================================
            try:
                # 'domcontentloaded' 比 'networkidle' 更快更稳定
                await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=45000)
            except TimeoutError:
                print("⚠️ 页面加载在45秒内未完成，但脚本将继续尝试执行...")
            
            print("基础页面导航完成或已超时。")

            # =========================================================
            # 已新增: 调用弹窗处理函数
            # =========================================================
            await close_potential_popups(page)
            
            # 等待一下，确保弹窗关闭后页面状态稳定
            await page.wait_for_timeout(3000)

            successful = await export_and_process_data(page)

            if successful:
                print("✅✅✅ 核心任务全部成功完成！")
            else:
                print("流程内部返回失败，正在截取当前页面...")
                await page.screenshot(path=ERROR_SCREENSHOT_FILE, full_page=True)
                print(f"✅ 截图已保存为 {ERROR_SCREENSHOT_FILE}")
                exit(1)

        except Exception as e:
            print(f"Playwright 主流程操作时出错: {e}")
            print("正在截取当前页面以供调试...")
            await page.screenshot(path=ERROR_SCREENSHOT_FILE, full_page=True)
            print(f"✅ 错误截图已保存为 {ERROR_SCREENSHOT_FILE}")
            exit(1)
        finally:
            print("操作完成，关闭浏览器...")
            await context.close()
            await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
