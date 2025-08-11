import json
import asyncio
import os
import pandas as pd
from datetime import datetime
import re 
from playwright.async_api import async_playwright, Page, TimeoutError, expect
import lark_oapi as lark
from lark_oapi.api.bitable.v1 import *

COOKIE_FILE = '来客.json'
BASE_URL = 'https://life.douyin.com/p/life_comment/management?groupid=1768205901316096'
EXPORT_FILE_NAME = "评价记录.xlsx"
ERROR_SCREENSHOT_FILE = "error_screenshot.png"

FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID")
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET")
FEISHU_APP_TOKEN = "MslRbdwPca7P6qsqbqgcvpBGnRh"
FEISHU_TABLE_ID = "tblqaCztMg19H545"

async def delete_all_records_from_bitable(client: lark.Client):
    """
    清空指定多维表格中的所有记录 (使用最健壮的实现)。
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
                lark.logger.error(f"获取记录列表失败, code: {list_resp.code}, msg: {list_resp.msg}\n详细响应体: {json.dumps(json.loads(list_resp.raw.content), indent=4, ensure_ascii=False)}")
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
        try:
            delete_req_body = BatchDeleteAppTableRecordRequestBody.builder().records(chunk_of_ids).build()
            delete_req: BatchDeleteAppTableRecordRequest = BatchDeleteAppTableRecordRequest.builder().app_token(FEISHU_APP_TOKEN).table_id(FEISHU_TABLE_ID).request_body(delete_req_body).build()
            delete_resp = client.bitable.v1.app_table_record.batch_delete(delete_req)
            if not delete_resp.success():
                lark.logger.error(f"批量删除记录失败, code: {delete_resp.code}, msg: {delete_resp.msg}")
        except Exception as e:
            print(f"❌ 删除记录时发生代码异常: {e}")
    print("--- 所有现有记录已清空 ---")
    return True

async def write_df_to_feishu_bitable(client: lark.Client, df: pd.DataFrame):
    """
    将评价数据DataFrame批量写入到飞书多维表格，并处理特定字段类型。
    """
    print("\n--- 开始将新数据【批量写入】飞书多维表格 ---")
    total_rows = len(df)
    if total_rows == 0:
        print("没有需要写入的新数据。")
        return
    print("正在准备所有待上传的记录...")
    records_to_create = []
    for index, row in df.iterrows():
        fields_data = {}
        for col_name in df.columns:
            value = row[col_name]
            if pd.isna(value):
                fields_data[col_name] = None
                continue
            if col_name == '用户等级':
                try:
                    fields_data[col_name] = int(value)
                except (ValueError, TypeError):
                    fields_data[col_name] = None
            elif col_name == '评价时间':
                try:
                    dt_object = pd.to_datetime(value)
                    dt_object_beijing = dt_object.tz_localize('Asia/Shanghai', ambiguous='infer')
                    fields_data[col_name] = int(dt_object_beijing.timestamp() * 1000)
                except (ValueError, TypeError):
                    fields_data[col_name] = None
            else:
                fields_data[col_name] = str(value)
                
        record = AppTableRecord.builder().fields(fields_data).build()
        records_to_create.append(record)
    batch_size = 500
    success_count = 0
    for i in range(0, len(records_to_create), batch_size):
        chunk = records_to_create[i:i + batch_size]
        print(f"正在处理第 {i + 1} 到 {i + len(chunk)} 条记录的批次...")
        try:
            request_body = BatchCreateAppTableRecordRequestBody.builder().records(chunk).build()
            request: BatchCreateAppTableRecordRequest = BatchCreateAppTableRecordRequest.builder().app_token(FEISHU_APP_TOKEN).table_id(FEISHU_TABLE_ID).request_body(request_body).build()
            response: BatchCreateAppTableRecordResponse = client.bitable.v1.app_table_record.batch_create(request)
            if not response.success():
                lark.logger.error(f"❌ 批次写入失败, code: {response.code}, msg: {response.msg}")
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
    执行全新的“导出评价-处理-上传-清理”流程。
    """
    print("\n--- 开始执行“导出评价”流程 ---")
    try:
        print(f"配置的导出日期范围为：当月 1 号到今天。")

        # 步骤 1-4: 导航与打开日期选择器 (保持不变)
        print("步骤 1: 点击 '全部评价'...")
        await page.get_by_text("全部评价").first.click()
        await page.wait_for_timeout(2000)
        print("步骤 2: 点击 '导出'...")
        await page.get_by_text("导出", exact=True).click()
        await page.wait_for_timeout(1000)
        print("步骤 3: 点击 '导出评价' 弹窗标题...")
        await page.locator("div").filter(has_text=re.compile(r"^导出评价$")).nth(1).click()
        await page.wait_for_timeout(2000)
        print("步骤 4: 点击日期范围选择器...")
        await page.locator("div:nth-child(2) > .byted-popper-trigger > .byted-input-wrapper > .byted-input-inner__wrapper").click()
        await page.wait_for_timeout(2000)
        
        # 步骤 5-6: 选择日期 (保持不变)
        print("步骤 5: 选择开始日期为当月 '1' 号...")
        await page.locator("div").filter(has_text=re.compile(r"^1$")).nth(2).click()
        await page.wait_for_timeout(2000)
        print(f"步骤 6: 选择结束日期为 '今天'...")
        await page.locator("div.byted-date-today:not(.byted-date-grid-prev):not(.byted-date-grid-next)").click()
        await page.wait_for_timeout(1000)

        # 步骤 7: 点击导出，打开新页面 (保持不变)
        print("步骤 7: 点击 '导出' 按钮以触发新页面...")
        async with page.context.expect_page() as new_page_info:
            await page.get_by_role("button", name="导出").click()
        new_page = await new_page_info.value
        
        # 步骤 8: 等待下载按钮可用 (保持不变)
        print("新页面已捕获，正在等待第一个 '下载' 按钮变为可用状态...")
        download_button = new_page.get_by_text("下载", exact=True).first
        await expect(download_button).to_be_enabled(timeout=120000)
        print("✅ '下载' 按钮已可用。")
        
        # 步骤 9: 点击下载 (保持不变)
        print("步骤 9: 点击 '下载' 按钮...")
        async with new_page.expect_download() as download_info:
            await download_button.click()
        download = await download_info.value

        if os.path.exists(EXPORT_FILE_NAME):
            os.remove(EXPORT_FILE_NAME)
        await download.save_as(EXPORT_FILE_NAME)
        print(f"✅ 文件已成功下载: {EXPORT_FILE_NAME}")

        # =========================================================
        # 已新增: 遍历并删除已导出的记录
        # =========================================================
        delete_buttons = new_page.locator("span.bt--q2Xcs:has-text('删除')")
        count = await delete_buttons.count()

        if count == 0:
            print("没有找到需要删除的记录。")
        else:
            print(f"找到 {count} 条已导出记录，准备逐一删除...")
            # 从上到下删除，所以我们总是点击第一个“删除”按钮
            for i in range(count):
                print(f"正在删除第 {i + 1}/{count} 条记录...")
                try:
                    # 定位第一个可见的删除按钮并点击
                    first_delete_button = delete_buttons.first
                    await first_delete_button.click()
                    await new_page.wait_for_timeout(500) # 等待确认弹窗出现

                    # 点击“确认删除”按钮
                    await new_page.get_by_role("button", name="确认删除").click()
                    
                    # 等待一下，让列表刷新。可以等待某个元素消失，或简单等待固定时间
                    # 这里使用固定等待，因为它更简单
                    await new_page.wait_for_timeout(2000) 
                    print(f"第 {i + 1} 条记录已删除。")
                except Exception as delete_error:
                    print(f"❌ 删除第 {i + 1} 条记录时出错: {delete_error}")
                    # 即使某条删除失败，也继续尝试下一条
                    continue
        
        print("✅ 已导出记录清理完毕。")
        
        # 步骤 10: 关闭新页面
        await new_page.close()
        
        # 后续的数据处理和上传部分保持不变
        print("\n步骤 10: 读取并处理Excel数据...")
        if not os.path.exists(EXPORT_FILE_NAME):
            print(f"❌ 错误：找不到下载的文件 {EXPORT_FILE_NAME}")
            return False
        
        df = pd.read_excel(EXPORT_FILE_NAME)

        print("步骤 11: 初始化飞书客户端并同步数据...")
        if not FEISHU_APP_ID or not FEISHU_APP_SECRET:
            print(f"❌ 错误：飞书的 App ID 或 App Secret 环境变量未设置！")
            return False
        feishu_client = lark.Client.builder().app_id(FEISHU_APP_ID).app_secret(FEISHU_APP_SECRET).build()

        # 先清空
        delete_ok = await delete_all_records_from_bitable(feishu_client)
        if not delete_ok:
            print("❌ 清空表格步骤失败，终止后续写入操作。")
            return False
        
        # 再写入
        if not df.empty:
            print("✅ 数据读取成功。")
            await write_df_to_feishu_bitable(feishu_client, df)
        else:
            print("✅ 下载的Excel文件为空，无需写入新数据。")
        
        print("--- 数据导出、处理与上传流程执行成功 ---\n")
        return True
        
    except Exception as e:
        print(f"❌ 在执行导出评价流程时发生错误: {e}")
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
            
            print("正在导航至新的评价管理页面...")
            try:
                await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=45000)
            except TimeoutError:
                print("⚠️ 页面加载在45秒内未完成，但脚本将继续尝试执行...")
            
            print("基础页面导航完成或已超时。")
            await page.wait_for_timeout(5000)

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

# 确保主程序被调用
if __name__ == '__main__':
    asyncio.run(main())
