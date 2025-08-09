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
# 已修复: 解决了 page_token=None 的问题
# =========================================================
async def delete_all_records_from_bitable(client: lark.Client):
    """
    清空指定多维表格中的所有记录。
    它通过循环分页查询获取所有记录ID，然后分批次批量删除。
    """
    print("\n--- 开始清空飞书多维表格中的所有现有记录 ---")
    all_record_ids = []
    page_token = None
    
    print("步骤 1/2: 正在获取所有记录ID...")
    while True:
        try:
            # --- 这是最核心的修复 ---
            # 1. 创建一个基础的请求构建器
            builder = ListAppTableRecordRequest.builder() \
                .app_token(FEISHU_APP_TOKEN) \
                .table_id(FEISHU_TABLE_ID) \
                .page_size(500)

            # 2. 只有当 page_token 有值时，才将其添加到构建器中
            if page_token:
                builder.page_token(page_token)
            
            # 3. 完成最终的请求构建
            list_req = builder.build()
            
            list_resp = client.bitable.v1.app_table_record.list(list_req)

            if not list_resp.success():
                lark.logger.error(
                    f"获取记录列表失败, code: {list_resp.code}, msg: {list_resp.msg}, log_id: {list_resp.get_log_id()}\n"
                    f"详细响应体 (Response Body):\n"
                    f"{json.dumps(json.loads(list_resp.raw.content), indent=4, ensure_ascii=False)}"
                )
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
            delete_req: BatchDeleteAppTableRecordRequest = BatchDeleteAppTableRecordRequest.builder() \
                .app_token(FEISHU_APP_TOKEN) \
                .table_id(FEISHU_TABLE_ID) \
                .request_body(delete_req_body) \
                .build()
            
            delete_resp = client.bitable.v1.app_table_record.batch_delete(delete_req)
            if not delete_resp.success():
                lark.logger.error(
                    f"批量删除记录失败, code: {delete_resp.code}, msg: {delete_resp.msg}, log_id: {delete_resp.get_log_id()}\n"
                    f"详细响应体 (Response Body):\n"
                    f"{json.dumps(json.loads(delete_resp.raw.content), indent=4, ensure_ascii=False)}"
                )
            else:
                lark.logger.info(f"✅ 成功删除 {len(getattr(delete_resp.data, 'records', []))} 条记录。")
        except Exception as e:
            print(f"❌ 删除记录时发生代码异常: {e}")

    print("--- 所有现有记录已清空 ---")
    return True

# ... 其他函数 write_df_to_feishu_bitable, export_and_process_data, main 保持不变 ...
async def write_df_to_feishu_bitable(client: lark.Client, df: pd.DataFrame):
    # 此函数内容无需修改
    print("\n--- 开始将新数据【批量写入】飞书多维表格 ---")
    total_rows = len(df)
    if total_rows == 0:
        print("没有需要写入的新数据。")
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
    # 此函数内容无需修改，但需要检查对删除函数的调用
    print("\n--- 开始执行数据导出、处理与上传流程 ---")
    try:
        # Playwright 操作部分
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

        # 步骤 7: 初始化飞书客户端
        if not FEISHU_APP_ID or not FEISHU_APP_SECRET:
            print("❌ 错误：飞书的 App ID 或 App Secret 环境变量未设置！")
            return False
        feishu_client = lark.Client.builder().app_id(FEISHU_APP_ID).app_secret(FEISHU_APP_SECRET).build()

        # 步骤 8: 清空表格
        delete_ok = await delete_all_records_from_bitable(feishu_client)
        if not delete_ok:
            print("❌ 清空表格步骤失败，终止后续写入操作。")
            return False

        # 步骤 9: 写入新数据
        if not df.empty:
            required_columns = ['核销门店', '商品名称', '退款申请时间', '退款申请原因', '订单实收(元)', '退款金额(元)']
            for col in required_columns:
                if col not in df.columns:
                    print(f"❌ 错误: 下载的Excel文件中缺少必需的列: '{col}'")
                    return False
            filtered_df = df[required_columns].copy()
            filtered_df['退款申请时间'] = pd.to_datetime(filtered_df['退款申请时间'])
            print("✅ 数据筛选完成。预览筛选后的数据 (前5行):")
            print(filtered_df.head().to_string())
            await write_df_to_feishu_bitable(feishu_client, filtered_df)
        else:
            print("✅ 下载的Excel文件为空，无需写入新数据。")
        
        print("--- 数据导出、处理与上传流程执行成功 ---\n")
        return True
    except Exception as e:
        print(f"❌ 在执行导出、处理与上传流程时发生错误: {e}")
        if 'new_page' in locals() and not new_page.is_closed():
            await new_page.screenshot(path=f"error_new_page_{ERROR_SCREENSHOT_FILE}")
        return False

async def main():
    # 此函数内容无需修改
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
            try:
                await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=45000)
            except TimeoutError:
                print("⚠️ 页面加载在45秒内未完成，但脚本将继续尝试执行...")
            print("基础页面导航完成或已超时。")
            # 假设 close_potential_popups 函数已定义
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
