import json
import asyncio
import os
import pandas as pd
# 导入 'expect' 用于更可靠的等待条件
from playwright.async_api import async_playwright, Page, TimeoutError, expect
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


async def close_potential_popups(page: Page):
    """
    根据您的要求，使用指定的定位器来检查并关闭可能出现的引导/升级弹窗。
    """
    print("\n--- 正在检查并关闭潜在的弹窗 ---")
    try:
        # 使用您提供的特定定位器来寻找关闭按钮
        close_button = page.locator(".byted-content-inner-wrapper > .byted-icon > svg").first
        
        # 使用一个较短的超时时间来快速检查
        print("正在查找弹窗关闭按钮...")
        await close_button.wait_for(state="visible", timeout=5000)
        
        print("检测到弹窗，正在尝试点击关闭...")
        await close_button.click()
        await page.wait_for_timeout(1000) # 等待关闭动画
        print("✅ 弹窗已关闭。")
        
    except TimeoutError:
        # 如果在5秒内找不到，说明弹窗没有出现，这是正常情况
        print("✅ 未检测到弹窗，继续执行。")
    except Exception as e:
        # 捕获其他可能的异常
        print(f"⚠️ 在尝试关闭弹窗时遇到一个非超时错误: {e}")


async def delete_all_records_from_bitable(client: lark.Client):
    """
    清空飞书多维表格中的所有记录。
    """
    print("\n--- 开始清空飞书多维表格中的所有现有记录 ---")
    all_record_ids = []
    page_token = None
    print("步骤 1/2: 正在获取所有记录ID...")
    while True:
        try:
            builder = ListAppTableRecordRequest.builder().app_token(FEISHU_APP_TOKEN).table_id(FEISHU_TABLE_ID).page_size(500)
            if page_token:
                builder.page_token(page_token)
            list_req = builder.build()
            list_resp = client.bitable.v1.app_table_record.list(list_req)
            if not list_resp.success():
                lark.logger.error(f"获取记录列表失败, code: {list_resp.code}, msg: {list_resp.msg}, log_id: {list_resp.get_log_id()}")
                return False
            items = getattr(list_resp.data, 'items', [])
            if items:
                all_record_ids.extend([item.record_id for item in items])
            if getattr(list_resp.data, 'has_more', False):
                page_token = list_resp.data.page_token
            else:
                break
        except Exception as e:
            print(f"❌ 获取记录时发生代码异常: {e}")
            return False
    if not all_record_ids:
        print("✅ 表格中没有记录，无需清空。")
        return True
    print(f"共找到 {len(all_record_ids)} 条记录待删除。")
    print("步骤 2/2: 正在分批删除记录...")
    batch_size = 500
    for i in range(0, len(all_record_ids), batch_size):
        chunk_of_ids = all_record_ids[i:i + batch_size]
        print(f"正在删除第 {i + 1} 到 {i + len(chunk_of_ids)} 条记录...")
        try:
            delete_req_body = BatchDeleteAppTableRecordRequestBody.builder().records(chunk_of_ids).build()
            delete_req: BatchDeleteAppTableRecordRequest = BatchDeleteAppTableRecordRequest.builder().app_token(FEISHU_APP_TOKEN).table_id(FEISHU_TABLE_ID).request_body(delete_req_body).build()
            delete_resp = client.bitable.v1.app_table_record.batch_delete(delete_req)
            if not delete_resp.success():
                lark.logger.error(f"批量删除记录失败, code: {delete_resp.code}, msg: {delete_resp.msg}, log_id: {delete_resp.get_log_id()}")
            else:
                lark.logger.info(f"✅ 成功删除 {len(getattr(delete_resp.data, 'records', []))} 条记录。")
        except Exception as e:
            print(f"❌ 删除记录时发生代码异常: {e}")
    print("--- 所有现有记录已清空 ---")
    return True

async def write_df_to_feishu_bitable(client: lark.Client, df: pd.DataFrame):
    """
    将筛选后的DataFrame数据批量写入到指定的飞书多维表格。
    """
    print("\n--- 开始将新数据【批量写入】飞书多维表格 ---")
    total_rows = len(df)
    if total_rows == 0:
        print("没有需要写入的新数据。")
        return
    print("正在为日期时间数据附加时区信息 (Asia/Shanghai)...")
    if df['退款申请时间'].dt.tz is None:
        df['退款申请时间'] = df['退款申请时间'].dt.tz_localize('Asia/Shanghai')
    else:
        df['退款申请时间'] = df['退款申请时间'].dt.tz_convert('Asia/Shanghai')
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
    """
    执行完整的“导出-处理-上传”流程，优化了等待逻辑和元素定位器。
    """
    print("\n--- 开始执行数据导出、处理与上传流程 ---")
    
    # 在所有操作开始前，先调用函数处理弹窗
    await close_potential_popups(page)

    new_page = None  # 提前声明变量以备在异常处理中使用
    try:
        # 步骤 1: 点击 '待处理' 选项卡并等待列表加载
        print("步骤 1: 点击 '待处理' 选项卡...")
        await page.locator('.byted-radio-tag:has-text("待处理")').click()
        export_data_button = page.get_by_role("button", name="导出数据")
        await export_data_button.wait_for(state="visible", timeout=15000)
        print("✅ '待处理' 列表加载完成。")

        # 步骤 2: 启动导出流程
        print("步骤 2: 点击 '导出数据' 按钮...")
        await export_data_button.click()

        # 步骤 3: 确认导出并捕获新打开的“导出记录”页面
        print("步骤 3: 点击 '确定导出'，并等待新页面打开...")
        confirm_export_button = page.get_by_role("button", name="确定导出")
        await confirm_export_button.wait_for(state="visible", timeout=5000)

        async with page.context.expect_page(timeout=10000) as new_page_info:
            await confirm_export_button.click()
        new_page = await new_page_info.value
        await new_page.wait_for_load_state("domcontentloaded")
        print("✅ 新页面（导出记录）已捕获。")

        # 步骤 4: 等待后台生成文件
        print("步骤 4: 等待后台生成导出文件（最长等待3分钟）...")
        first_row = new_page.locator("tbody > tr").first
        # 注意：'td:nth-child(4)' 指的是第4列，即状态列。如果页面结构变化，可能需要调整
        status_cell = first_row.locator("td:nth-child(4)")
        await expect(status_cell).to_contain_text("导出成功", timeout=180000)
        print("✅ 文件已成功生成！")

        # 步骤 5: 文件生成后，再进行下载
        print("步骤 5: 点击 '下载' 按钮...")
        download_button = first_row.get_by_role("button", name="下载")
        async with new_page.expect_download(timeout=30000) as download_info:
            await download_button.click()
        download = await download_info.value
        
        if os.path.exists(EXPORT_FILE_NAME):
            os.remove(EXPORT_FILE_NAME)
        await download.save_as(EXPORT_FILE_NAME)
        print(f"✅ 文件已成功下载: {EXPORT_FILE_NAME}")

        # 步骤 6: 清理所有已导出的记录
        print("\n步骤 6: 开始清理所有导出记录...")
        while True:
            delete_buttons = new_page.get_by_role("button", name="删除")
            count = await delete_buttons.count()
            if count == 0:
                print("✅ 没有需要删除的记录，清理完成。")
                break
            
            print(f"找到 {count} 条记录，正在删除第一条...")
            try:
                await delete_buttons.first.click()
                confirm_delete_button = new_page.get_by_role("button", name="确认删除")
                await confirm_delete_button.wait_for(state="visible")
                await confirm_delete_button.click()
                
                await expect(delete_buttons).to_have_count(count - 1, timeout=10000)
                print(f"记录已删除。剩余 {count - 1} 条。")
            except Exception as delete_error:
                print(f"❌ 删除记录时出错: {delete_error}。将刷新页面后重试...")
                await new_page.reload()
                await new_page.wait_for_load_state("domcontentloaded")

        print("✅ 所有导出记录清理完毕。")
        await new_page.close()
        print("导出记录页面已关闭。")

        # 步骤 7: 读取Excel并上传到飞书
        print("\n步骤 7: 读取并筛选Excel数据...")
        if not os.path.exists(EXPORT_FILE_NAME):
            print(f"❌ 错误：找不到下载的文件 {EXPORT_FILE_NAME}")
            return False
        
        df = pd.read_excel(EXPORT_FILE_NAME)
        if not df.empty:
            if not FEISHU_APP_ID or not FEISHU_APP_SECRET:
                print("❌ 错误：飞书的 App ID 或 App Secret 环境变量未设置！")
                return False
            feishu_client = lark.Client.builder().app_id(FEISHU_APP_ID).app_secret(FEISHU_APP_SECRET).build()
            
            if not await delete_all_records_from_bitable(feishu_client):
                print("❌ 清空表格步骤失败，终止后续写入操作。")
                return False

            required_columns = ['核销门店', '商品名称', '退款申请时间', '退款申请原因', '订单实收(元)', '退款金额(元)']
            if not all(col in df.columns for col in required_columns):
                print(f"❌ 错误: 下载的Excel文件中缺少必需的列。")
                return False
            
            filtered_df = df[required_columns].copy()
            filtered_df['退款申请时间'] = pd.to_datetime(filtered_df['退款申请时间'])
            print("✅ 数据筛选完成。预览筛选后的数据 (前5行):")
            print(filtered_df.head().to_string())
            await write_df_to_feishu_bitable(feishu_client, filtered_df)
        else:
            print("✅ 下载的Excel文件为空，清空线上表格后结束。")
            if not FEISHU_APP_ID or not FEISHU_APP_SECRET:
                print("❌ 错误：飞书的 App ID 或 App Secret 环境变量未设置！")
                return False
            feishu_client = lark.Client.builder().app_id(FEISHU_APP_ID).app_secret(FEISHU_APP_SECRET).build()
            await delete_all_records_from_bitable(feishu_client)
            
        print("--- 数据导出、处理与上传流程执行成功 ---\n")
        return True

    except Exception as e:
        print(f"❌ 在执行导出、处理与上传流程时发生错误: {e}")
        if new_page and not new_page.is_closed():
            await new_page.screenshot(path=f"error_new_page.png")
            print("✅ 已保存新页面的错误截图。")
        if page and not page.is_closed():
            await page.screenshot(path=ERROR_SCREENSHOT_FILE)
            print(f"✅ 已保存主页面的错误截图。")
        return False

async def main():
    """
    主执行函数
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
            print(f"正在导航至目标页面: {BASE_URL}")
            try:
                await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=45000)
            except TimeoutError:
                print("⚠️ 页面加载在45秒内未完成，但脚本将继续尝试执行...")
            print("页面导航完成或已超时。")
            
            successful = await export_and_process_data(page)
            
            if successful:
                print("✅✅✅ 核心任务全部成功完成！")
            else:
                print("❌ 流程执行失败，请检查上面打印的错误日志和截图。")
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
