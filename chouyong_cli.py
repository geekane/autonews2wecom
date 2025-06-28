# 文件名: chouyong_cli.py (最终正确版 - 修正API调用错误)

import logging
import json
import os
import time
import datetime
import asyncio
import traceback
import sys
import re
import concurrent.futures

# --- 库导入和基础设置 ---
try:
    import openpyxl
    from playwright.async_api import async_playwright, expect
    import pandas as pd
    import requests
    import lark_oapi as lark
    from lark_oapi.api.bitable.v1 import *
except ImportError as e:
    missing_lib = e.name
    print(f"致命错误: 缺少 '{missing_lib}' 库。请运行 'pip install -r requirements.txt' 后重试。")
    sys.exit(1)

CONFIG_FILE = "config.json"
COOKIE_FILE = "林客.json"
LOG_DIR = "logs"
DEBUG_DIR = "debug_artifacts"

for d in [LOG_DIR, DEBUG_DIR]:
    if not os.path.exists(d):
        os.makedirs(d)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, f"run_log_{datetime.date.today().strftime('%Y-%m-%d')}.log"), mode='a', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)


class CliRunner:
    def __init__(self):
        self.configs = self.load_configs()
        self.feishu_client = None

    def load_configs(self):
        logging.info(f"正在从 {CONFIG_FILE} 加载配置...")
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logging.error(f"加载配置文件 {CONFIG_FILE} 失败: {e}")
            sys.exit(1)

    # ==============================================================================
    # 辅助函数
    # ==============================================================================
    def _init_feishu_client(self):
        app_id = self.configs.get("feishu_app_id")
        app_secret = self.configs.get("feishu_app_secret")
        if not app_id or not app_secret:
            logging.error("飞书配置错误。")
            return False
        logging.info("正在初始化飞书客户端...")
        self.feishu_client = lark.Client.builder().app_id(app_id).app_secret(app_secret).log_level(lark.LogLevel.WARNING).build()
        logging.info("飞书客户端初始化成功。")
        return True

    async def _get_empty_commission_records_from_feishu(self):
        source_field = self.configs["get_commission_source_field"]
        target_field = self.configs["get_commission_target_field"]
        logging.info(f"开始从飞书查询 '{target_field}' 为空的记录...")
        all_records = []
        page_token = None
        while True:
            try:
                filter_condition = Condition.builder().field_name(target_field).operator("isEmpty").value([]).build()
                filter_obj = FilterInfo.builder().conjunction("and").conditions([filter_condition]).build()
                request_body = SearchAppTableRecordRequestBody.builder().field_names([source_field]).filter(filter_obj).build()
                request_builder = SearchAppTableRecordRequest.builder().app_token(self.configs['feishu_app_token']).table_id(self.configs['feishu_table_id']).page_size(500).request_body(request_body)
                if page_token:
                    request_builder.page_token(page_token)
                request = request_builder.build()
                response = self.feishu_client.bitable.v1.app_table_record.search(request)
                if not response.success():
                    logging.error(f"查询飞书记录失败: Code={response.code}, Msg={response.msg}")
                    return None
                items = response.data.items or []
                for item in items:
                    if source_field in item.fields and item.fields[source_field]:
                        product_id_text = item.fields[source_field][0].get('text', '')
                        if product_id_text:
                           all_records.append({"id": product_id_text, "record_id": item.record_id})
                if response.data.has_more:
                    page_token = response.data.page_token
                else: 
                    break
            except Exception as e:
                logging.error(f"查询飞书记录时发生异常: {e}", exc_info=True)
                return None
        return all_records

    async def _update_feishu_record(self, record_id, commission_info):
        target_field = self.configs["get_commission_target_field"]
        try:
            record = AppTableRecord.builder().fields({target_field: str(commission_info)}).build()
            req = UpdateAppTableRecordRequest.builder().app_token(self.configs['feishu_app_token']).table_id(self.configs['feishu_table_id']).record_id(record_id).request_body(record).build()
            response = self.feishu_client.bitable.v1.app_table_record.update(req)
            if not response.success():
                logging.error(f"更新飞书记录 {record_id} 失败: Code={response.code}, Msg={response.msg}")
                return False
            return True
        except Exception as e:
            logging.error(f"更新飞书记录 {record_id} 时发生异常: {e}", exc_info=True)
            return False
            
    # ==============================================================================
    # 严格遵循您提供的成功逻辑，并修正API调用错误
    # ==============================================================================
    async def _process_id_on_page(self, page, product_id, max_retries, retry_delay):
        for attempt in range(max_retries + 1):
            try:
                if attempt > 0:
                    logging.info(f"    -> [ID: {product_id}] 第 {attempt + 1}/{max_retries + 1} 次尝试...")
                
                input_field = page.get_by_role("textbox", name="商品名称/ID")
                await expect(input_field).to_be_visible(timeout=20000)
                await input_field.clear()
                await input_field.fill(str(product_id))
                
                await page.get_by_test_id("查询").click()
                
                id_in_result_locator = page.locator(".okee-lp-Table-Body .okee-lp-Table-Row").first.get_by_text(str(product_id), exact=True)
                await expect(id_in_result_locator).to_be_visible(timeout=30000)
                
                commission_status_locator = page.locator(".okee-lp-Table-Cell > .lp-flex > .okee-lp-tag").first
                await expect(commission_status_locator).to_be_visible(timeout=15000)
                
                status_text = (await commission_status_locator.text_content() or "").strip()
                status_result = "已设置" if status_text == "已设置" else f"未设置 ({status_text})"
                commission_info = "未找到"
                
                if status_result == "已设置":
                    channel_info_locator = page.locator("div.lp-flex.lp-items-center:has-text('%')").first
                    
                    # --- 核心修正：使用正确的API进行等待 ---
                    try:
                        # expect().to_be_visible() 是正确的带超时的等待方法
                        await expect(channel_info_locator).to_be_visible(timeout=5000)
                        commission_info = (await channel_info_locator.text_content() or "").strip().replace('"', '')
                    except Exception:
                        # 如果5秒内找不到，说明没有这个元素，是正常情况
                        logging.warning(f"    ! [ID: {product_id}] 状态为'已设置'但未找到佣金比例详情。")
                        commission_info = "已设置但无详细比例"
                        
                return status_result, commission_info

            except Exception as e:
                error_msg = str(e).splitlines()[0]
                logging.warning(f"    ! [ID: {product_id}] 第 {attempt + 1} 次尝试失败: {error_msg}")
                if attempt < max_retries:
                    logging.info(f"    将在 {retry_delay} 秒后重试...")
                    await asyncio.sleep(retry_delay)
                else:
                    logging.error(f"    !! [ID: {product_id}] 所有重试均失败。")
                    try:
                        screenshot_path = os.path.join(DEBUG_DIR, f"error_screenshot_{product_id}_final_attempt.png")
                        await page.screenshot(path=screenshot_path, full_page=True)
                        logging.info(f"      最终失败截图已保存至: {screenshot_path}")
                    except Exception as screenshot_error:
                        logging.error(f"      尝试保存最终失败截图失败: {screenshot_error}")
                    return "查询失败", error_msg

        return "查询失败", "未知错误"

    async def task_get_commission(self):
        logging.info("启动查询并回写佣金任务...")
        if not self._init_feishu_client():
            return
        
        try:
            tasks_to_process = await self._get_empty_commission_records_from_feishu()
            if not tasks_to_process:
                logging.info("未找到待处理记录，任务结束。")
                return
            logging.info(f"共从飞书获取到 {len(tasks_to_process)} 条待处理记录。")

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                
                logging.info(f"正在从文件 '{COOKIE_FILE}' 加载登录状态...")
                if not os.path.exists(COOKIE_FILE):
                    raise FileNotFoundError(f"Cookie文件 '{COOKIE_FILE}' 未找到。")
                
                context = await browser.new_context(storage_state=COOKIE_FILE)
                logging.info("成功加载登录状态。")
                
                page = await context.new_page()
                
                base_url = f"https://www.life-partner.cn/vmok/order-detail?from_page=order_management&merchantId={self.configs['douyin_account_id']}&orderId=7494097018429261839&queryScene=0&skuOrderId=1829003050957856&tabName=ChargeSetting"
                logging.info(f"导航到目标页面: {base_url}")
                await page.goto(base_url, timeout=120000, wait_until="domcontentloaded")
                
                logging.info("页面导航完成，给予5秒稳定时间...")
                await page.wait_for_timeout(5000)
                
                total_tasks = len(tasks_to_process)
                for i, task in enumerate(tasks_to_process):
                    product_id, record_id = task["id"], task["record_id"]
                    logging.info(f"--- [进度 {i+1}/{total_tasks}] 开始处理ID: {product_id} ---")
                    
                    status, commission_info = await self._process_id_on_page(page, product_id, self.configs.get("max_retries", 3), 2)
                    
                    if status == "已设置":
                        logging.info(f"  -> ID {product_id} 查询到佣金: {commission_info}，回写飞书...")
                        success = await self._update_feishu_record(record_id, commission_info)
                        if success: logging.info(f"  ✔ 回写记录 {record_id} 成功。")
                        else: logging.error(f"  ❌ 回写记录 {record_id} 失败。")
                    else:
                        logging.info(f"  -> ID {product_id} 未查询到佣金 ({status})，跳过回写。")
                
                await browser.close()
        except Exception as e:
            logging.error(f"任务主流程发生错误: {e}", exc_info=True)
        finally:
            self.feishu_client = None
            logging.info("\n获取佣金任务执行完毕。")

# ==============================================================================
# 程序主入口
# ==============================================================================
async def main():
    runner = CliRunner()
    # 为保持简单，暂时只运行第二个任务
    # await runner.task_sync_feishu_ids() 
    await runner.task_get_commission()
    logging.info("所有任务执行完毕。")

if __name__ == "__main__":
    asyncio.run(main())
