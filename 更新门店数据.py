import asyncio
import json
import logging
import os
import pandas as pd
from playwright.async_api import async_playwright, TimeoutError
import lark_oapi as lark
from lark_oapi.api.bitable.v1 import *
from typing import List, Dict
import functools

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')
DOUYIN_COOKIE_FILE = '来客.json'
DOUYIN_TARGET_URL = "https://life.douyin.com/p/poi-manage/home?groupid=1768205901316096"
DOWNLOAD_DIR = "downloads"
DOWNLOADED_FILENAME = "门店基础数据.xlsx"
FEISHU_APP_ID = os.getenv("FEISHU_APP_ID")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET")
FEISHU_APP_TOKEN = "MslRbdwPca7P6qsqbqgcvpBGnRh"
FEISHU_TABLE_ID = "tblW3GOgcvSQMPJF"

# --- 2. 飞书多维表格操作模块 (改回使用 List API，更稳定) ---
class FeishuBitableManager:
    def __init__(self, app_id: str, app_secret: str):
        self.client = lark.Client.builder().app_id(app_id).app_secret(app_secret).log_level(lark.LogLevel.INFO).build()

    async def _run_sync_in_executor(self, sync_func, *args, **kwargs):
        loop = asyncio.get_running_loop()
        p = functools.partial(sync_func, *args, **kwargs)
        return await loop.run_in_executor(None, p)
    
    # [修改] 改回使用 List API，这是获取全部记录ID最直接、最稳定的方法
    async def _get_all_record_ids(self, app_token: str, table_id: str) -> List[str]:
        """遍历所有分页，获取指定表格中所有记录的ID。"""
        logging.info("开始使用 List API 获取表格中所有现有记录的ID...")
        record_ids = []
        page_token = None
        has_more = True
        
        while has_more:
            builder = ListAppTableRecordRequest.builder() \
                .app_token(app_token) \
                .table_id(table_id) \
                .page_size(500)

            if page_token:
                builder.page_token(page_token)
            
            req = builder.build()
            
            resp: ListAppTableRecordResponse = await self._run_sync_in_executor(
                self.client.bitable.v1.app_table_record.list, req
            )
            
            if not resp.success():
                logging.error(f"List API 获取记录列表失败: {resp.code}, {resp.msg}, log_id: {resp.get_log_id()}")
                return []

            if resp.data.items:
                for item in resp.data.items:
                    record_ids.append(item.record_id)
            
            has_more = resp.data.has_more
            page_token = resp.data.page_token
            logging.info(f"   - 已获取 {len(record_ids)} 条记录ID... (更多: {has_more})")
        
        logging.info(f"共获取到 {len(record_ids)} 个记录ID。")
        return record_ids

    async def clear_table(self, app_token: str, table_id: str):
        """清空指定多维表格的所有记录。"""
        logging.info(f"准备清空表格: {table_id}")
        record_ids = await self._get_all_record_ids(app_token, table_id)
        
        if not record_ids:
            logging.info("表格已为空，无需清空。")
            return

        logging.info(f"开始删除 {len(record_ids)} 条记录...")
        for i in range(0, len(record_ids), 500):
            chunk = record_ids[i:i+500]
            logging.info(f"   - 正在删除第 {i+1} 到 {i+len(chunk)} 条记录...")
            
            req_body = BatchDeleteAppTableRecordRequestBody.builder().records(chunk).build()
            req = BatchDeleteAppTableRecordRequest.builder() \
                .app_token(app_token) \
                .table_id(table_id) \
                .request_body(req_body) \
                .build()
            
            resp: BatchDeleteAppTableRecordResponse = await self._run_sync_in_executor(
                self.client.bitable.v1.app_table_record.batch_delete, req
            )
            
            if not resp.success():
                logging.error(f"批量删除记录失败: {resp.code}, {resp.msg}, log_id: {resp.get_log_id()}")
            else:
                logging.info(f"   - 成功删除 {len(chunk)} 条记录。")
        
        logging.info("表格清空完成。")


    async def batch_add_records(self, app_token: str, table_id: str, records_data: List[Dict]):
        if not records_data: logging.warning("没有数据需要添加到飞书多维表格。"); return
        logging.info(f"准备向表格 {table_id} 新增 {len(records_data)} 条记录...")
        for i in range(0, len(records_data), 500):
            chunk = records_data[i:i+500]
            request_records = [AppTableRecord.builder().fields(record).build() for record in chunk]
            req_body = BatchCreateAppTableRecordRequestBody.builder().records(request_records).build()
            req = BatchCreateAppTableRecordRequest.builder().app_token(app_token).table_id(table_id).request_body(req_body).build()
            resp: BatchCreateAppTableRecordResponse = await self._run_sync_in_executor(self.client.bitable.v1.app_table_record.batch_create, req)
            if not resp.success():
                logging.error(f"批量添加记录失败: {resp.code}, {resp.msg}, log_id: {resp.get_log_id()}")
                lark.logger.error(f"resp: \n{json.dumps(json.loads(resp.raw.content), indent=4, ensure_ascii=False)}")
            else: logging.info(f"   - 成功新增 {len(chunk)} 条记录。")
        logging.info("所有记录新增完成。")

# --- 3. 抖音数据下载模块 (无变化) ---
async def download_from_douyin(cookie_file: str, url: str, download_path: str) -> bool:
    # ... 此处代码与之前完全相同，省略以节省空间 ...
    logging.info("--- 开始执行抖音数据下载任务 ---")
    if not os.path.exists(cookie_file): logging.error(f"错误: Cookie 文件 '{cookie_file}' 未找到。"); return False
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, slow_mo=100)
        context = await browser.new_context(accept_downloads=True)
        try:
            with open(cookie_file, 'r', encoding='utf-8') as f: storage_state = json.load(f)
            await context.add_cookies(storage_state['cookies'])
            logging.info(f"成功从 '{cookie_file}' 加载 Cookies。")
        except Exception as e:
            logging.error(f"加载 Cookie 文件时出错: {e}"); await browser.close(); return False
        page = await context.new_page()
        try:
            logging.info(f"正在导航到目标页面: {url}")
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            logging.info("页面DOM加载完成，开始查找元素...")

            try:
                logging.info("正在尝试点击 '知道了' 按钮 (如果存在)...")
                await page.get_by_text("知道了").click(timeout=5000)
                logging.info("   - '知道了' 按钮已点击。")
            except TimeoutError:
                logging.info("   - 未找到 '知道了' 按钮或超时，属于正常情况，继续执行。")

            async with page.expect_download(timeout=90000) as download_info:
                logging.info("正在定位并点击 '导出数据' 按钮...")
                await page.get_by_role("button", name="导出数据").click()
                logging.info("   - 点击 '导出数据' 已触发，等待文件下载完成...")
                download = await download_info.value
            
            await download.save_as(download_path)
            logging.info(f"文件下载成功 (原始名: {download.suggested_filename})")
            logging.info(f"文件已保存至: '{download_path}'")
            return True
        except TimeoutError as e: logging.error(f"操作超时: 等待页面元素超时。 {e}"); return False
        except Exception as e: logging.error(f"在自动化流程中发生未知错误: {e}"); return False
        finally: await browser.close(); logging.info("抖音下载浏览器已关闭。")

# --- 4. 数据处理模块 (无变化) ---
def process_downloaded_data(filepath: str) -> List[Dict]:
    # ... 此处代码与之前完全相同，省略以节省空间 ...
    TARGET_COLUMN = "门店名称"
    logging.info(f"正在处理下载的Excel文件，目标列: '{TARGET_COLUMN}'")
    
    if not os.path.exists(filepath):
        logging.error(f"文件处理失败：文件未找到于 '{filepath}'")
        return []

    records_to_add = []
    try:
        df = pd.read_excel(filepath)
        logging.info(f"成功使用pandas加载Excel文件，共 {len(df)} 行，列名: {list(df.columns)}")

        if TARGET_COLUMN not in df.columns:
            logging.error(f"错误: 下载的Excel文件中未找到目标列 '{TARGET_COLUMN}'。请检查下载的文件内容。")
            return []
        
        store_names = df[TARGET_COLUMN].dropna().unique()
        
        for name in store_names:
            clean_name = str(name).strip()
            if clean_name:
                record = {TARGET_COLUMN: clean_name}
                records_to_add.append(record)

        logging.info(f"数据处理完成，共准备了 {len(records_to_add)} 条不重复的 '{TARGET_COLUMN}' 记录。")
        
        if records_to_add:
            logging.info("--- 最终发送给飞书的第一条记录预览 ---")
            print(json.dumps(records_to_add[0], indent=2, ensure_ascii=False))
            logging.info("--- 预览结束 ---")
        return records_to_add

    except Exception as e:
        logging.error(f"使用 pandas 处理Excel文件时发生错误: {e}")
        return []

# --- 5. 主流程 (无变化) ---
async def main():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    download_filepath = os.path.join(DOWNLOAD_DIR, DOWNLOADED_FILENAME)
    
    success = await download_from_douyin(DOUYIN_COOKIE_FILE, DOUYIN_TARGET_URL, download_filepath)
    if not success: logging.error("抖音数据下载失败，任务终止。"); return
        
    records_to_add = process_downloaded_data(download_filepath)
    if not records_to_add: logging.error("数据处理失败或无有效数据，任务终止。"); return
        
    logging.info("\n--- 开始执行飞书数据同步任务 ---")
    feishu_manager = FeishuBitableManager(FEISHU_APP_ID, FEISHU_APP_SECRET)
    
    await feishu_manager.clear_table(FEISHU_APP_TOKEN, FEISHU_TABLE_ID)
    
    await feishu_manager.batch_add_records(FEISHU_APP_TOKEN, FEISHU_TABLE_ID, records_to_add)
    
    logging.info("\n--- 所有任务执行完毕 ---")

if __name__ == "__main__":
    asyncio.run(main())
