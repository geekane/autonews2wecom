# 文件名: chouyong_cli.py (最终正确版 - 多阶段截图)

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
        self.douyin_access_token = None
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
    # 第2步: 飞书 | 同步商品ID (所有相关函数)
    # ==============================================================================
    def _get_douyin_client_token(self, douyin_configs):
        url = "https://open.douyin.com/oauth/client_token/"
        payload = {"client_key": douyin_configs['douyin_key'], "client_secret": douyin_configs['douyin_secret'], "grant_type": "client_credential"}
        headers = {"Content-Type": "application/json"}
        logging.info("开始获取抖音 Client Token...")
        try:
            response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=10)
            response.raise_for_status()
            data = response.json()
            if data.get("data") and "access_token" in data["data"]:
                self.douyin_access_token = data["data"]["access_token"]
                logging.info("成功获取抖音 Client Token。")
                return True
            else:
                error_msg = data.get("data", {}).get("description", "获取Token失败")
                logging.error(f"获取抖音Token失败: {error_msg}")
                return False
        except requests.RequestException as e:
            logging.error(f"请求抖音Token时出错: {e}")
            return False

    def _load_poi_ids_from_excel(self, file_path):
        try:
            df = pd.read_excel(file_path, header=0, usecols=[0], dtype=str)
            poi_ids = df.iloc[:, 0].dropna().astype(str).str.strip().tolist()
            if not poi_ids:
                logging.error(f"未能从Excel文件 '{file_path}' 的第一列读取到任何POI ID。")
                return []
            logging.info(f"成功从 '{file_path}' 加载 {len(poi_ids)} 个POI ID。")
            return poi_ids
        except Exception as e:
            logging.error(f"读取Excel '{file_path}' 时出错: {e}")
            return []

    def _query_douyin_online_products(self, params):
        if not self.douyin_access_token:
            logging.error("抖音 Access Token 缺失, 无法查询。")
            return {"success": False, "message": "抖音 Access Token 缺失"}
        url = "https://open.douyin.com/goodlife/v1/goods/product/online/query/"
        headers = {'Content-Type': 'application/json', 'access-token': self.douyin_access_token}
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            response_json = response.json()
            if response_json.get("BaseResp", {}).get("StatusCode") == 0:
                return {"success": True, **response_json.get("data", {})}
            else:
                error_message = response_json.get("BaseResp", {}).get("StatusMessage", "未知API错误")
                logging.error(f"查询抖音API返回错误: {error_message}. 完整响应: {response_json}")
                return {"success": False, "message": f"API错误: {error_message}"}
        except Exception as e:
            logging.error(f"查询抖音线上商品时发生严重错误: {e}", exc_info=True)
            return {"success": False, "message": f"请求错误: {e}"}

    def _get_all_product_ids_for_poi(self, poi_id, account_id):
        all_product_ids = set()
        current_cursor, page = "", 1
        while True:
            logging.info(f"    查询POI[{poi_id}] 第 {page} 页...")
            params = {"account_id": account_id, "poi_ids": [poi_id], "count": 50, "cursor": current_cursor}
            result = self._query_douyin_online_products(params)
            if result.get("success"):
                for p_info in result.get("products", []):
                    if product_id_val := p_info.get("product", {}).get("product_id"):
                        all_product_ids.add(str(product_id_val))
                if result.get("has_more"):
                    current_cursor, page = result.get("next_cursor", ""), page + 1
                    time.sleep(0.2)
                else:
                    break
            else:
                logging.error(f"    错误：查询POI[{poi_id}]失败: {result.get('message')}")
                return set()
        logging.info(f"    POI[{poi_id}]查询完成，找到 {len(all_product_ids)} 个商品ID。")
        return all_product_ids

    def _init_feishu_client(self):
        app_id = self.configs.get("feishu_app_id")
        app_secret = self.configs.get("feishu_app_secret")
        if not app_id or not app_secret:
            logging.error("飞书配置错误: 请在 config.json 或 GitHub Secrets 中提供 feishu_app_id 和 feishu_app_secret。")
            return False
        logging.info("正在初始化飞书客户端...")
        self.feishu_client = lark.Client.builder().app_id(app_id).app_secret(app_secret).log_level(lark.LogLevel.WARNING).build()
        logging.info("飞书客户端初始化成功。")
        return True

    def _add_records_to_feishu_table(self, records_to_add, app_token, table_id):
        if not records_to_add: return {"success": True}
        if not self.feishu_client: return {"success": False, "message": "飞书客户端未初始化"}
        try:
            request_body = BatchCreateAppTableRecordRequestBody.builder().records(records_to_add).build()
            req = BatchCreateAppTableRecordRequest.builder().app_token(app_token).table_id(table_id).request_body(request_body).build()
            res = self.feishu_client.bitable.v1.app_table_record.batch_create(req)
            if not res.success():
                error_details = f"Code={res.code}, Msg={res.msg}, LogID={res.get_log_id()}"
                logging.error(f"新增记录到飞书失败: {error_details}")
                return {"success": False, "message": f"新增失败: {res.msg} (Code: {res.code})"}
            logging.info(f"成功向飞书表格新增 {len(res.data.records)} 条记录。")
            return {"success": True}
        except Exception as e:
            logging.error(f"写入飞书时发生未知错误: {e}", exc_info=True)
            return {"success": False, "message": f"未知错误: {e}"}
            
    def _get_all_existing_product_ids_from_feishu(self):
        field_name = self.configs['feishu_field_name']
        logging.info(f"开始从飞书获取已存在的商品ID，目标列: '{field_name}'...")
        existing_ids = set()
        page_token = None
        while True:
            try:
                request_body = SearchAppTableRecordRequestBody.builder().field_names([field_name]).build()
                request_builder = SearchAppTableRecordRequest.builder().app_token(self.configs['feishu_app_token']).table_id(self.configs['feishu_table_id']).page_size(500).request_body(request_body)
                if page_token:
                    request_builder.page_token(page_token)
                request = request_builder.build()
                response = self.feishu_client.bitable.v1.app_table_record.search(request)
                if not response.success():
                    logging.error(f"查询飞书现有记录失败: Code={response.code}, Msg={response.msg}")
                    return None
                items = response.data.items or []
                for item in items:
                    if field_name in item.fields and item.fields[field_name]:
                        product_id_text = item.fields[field_name][0].get('text', '')
                        if product_id_text:
                            existing_ids.add(product_id_text.strip())
                if response.data.has_more:
                    page_token = response.data.page_token
                else:
                    break
            except Exception as e:
                logging.error(f"查询飞书现有记录时发生异常: {e}", exc_info=True)
                return None
        logging.info(f"成功从飞书获取到 {len(existing_ids)} 个已存在的商品ID。")
        return existing_ids

    async def task_sync_feishu_ids(self):
        logging.info("==================================================")
        logging.info("========== 开始执行步骤2: 同步商品ID到飞书 ==========")
        logging.info("==================================================")
        try:
            if not self._init_feishu_client(): return
            douyin_configs = {"douyin_key": self.configs.get("douyin_key"), "douyin_secret": self.configs.get("douyin_secret"), "douyin_account_id": self.configs.get("douyin_account_id")}
            if not self._get_douyin_client_token(douyin_configs): return
            existing_feishu_ids = self._get_all_existing_product_ids_from_feishu()
            if existing_feishu_ids is None:
                logging.error("无法从飞书获取现有数据，任务中止。")
                return
            poi_excel_path = self.configs['feishu_poi_excel']
            if not os.path.exists(poi_excel_path):
                logging.error(f"找不到门店ID文件: {poi_excel_path}")
                return
            poi_ids = self._load_poi_ids_from_excel(poi_excel_path)
            if not poi_ids: return
            poi_batch_size = self.configs.get('poi_batch_size', 20)
            total_poi_batches = (len(poi_ids) + poi_batch_size - 1) // poi_batch_size
            for i in range(0, len(poi_ids), poi_batch_size):
                poi_chunk = poi_ids[i:i + poi_batch_size]
                current_batch_num = i // poi_batch_size + 1
                logging.info(f"\n--- 开始处理POI批次 {current_batch_num}/{total_poi_batches} ({len(poi_chunk)}个POI) ---")
                all_product_ids_for_chunk = set()
                with concurrent.futures.ThreadPoolExecutor(max_workers=self.configs.get('feishu_max_workers', 5)) as executor:
                    future_to_poi = {executor.submit(self._get_all_product_ids_for_poi, poi, douyin_configs['douyin_account_id']): poi for poi in poi_chunk}
                    for future in concurrent.futures.as_completed(future_to_poi):
                        product_ids_set = future.result()
                        if product_ids_set: all_product_ids_for_chunk.update(product_ids_set)
                ids_to_add = all_product_ids_for_chunk - existing_feishu_ids
                if not ids_to_add:
                    logging.info(f"--- POI批次 {current_batch_num} 未查询到任何【新的】商品ID可写入，跳过。 ---")
                    logging.info(f"  (本次从抖音查询到 {len(all_product_ids_for_chunk)} 个, 但均已存在于飞书)")
                    continue
                logging.info(f"POI批次 {current_batch_num} 查询结束，共收集到 {len(all_product_ids_for_chunk)} 个ID，其中 {len(ids_to_add)} 个是新ID，准备写入飞书...")
                records_to_create = [AppTableRecord.builder().fields({self.configs['feishu_field_name']: str(pid)}).build() for pid in ids_to_add]
                for j in range(0, len(records_to_create), 500):
                    record_batch = records_to_create[j:j+500]
                    logging.info(f"  向飞书写入数据... (部分 {j//500 + 1})")
                    add_result = self._add_records_to_feishu_table(record_batch, self.configs['feishu_app_token'], self.configs['feishu_table_id'])
                    if not add_result["success"]:
                        logging.error(f"  写入飞书失败: {add_result.get('message')}"); break
                    else:
                        existing_feishu_ids.update(ids_to_add)
            logging.info("\n步骤2: 所有POI批次处理完成！")
        except Exception as e:
            logging.error(f"步骤2主线程出错: {e}", exc_info=True)
        finally:
            self.feishu_client = None

    # ==============================================================================
    # 第3步: 查询 | 获取佣金 (所有相关函数)
    # ==============================================================================
    
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
                    logging.error(f"查询飞书记录失败: Code={response.code}, Msg={response.msg}, LogId={response.get_log_id()}")
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
                logging.error(f"查询飞书记录时发生异常: {traceback.format_exc()}")
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

    async def _process_id_on_page(self, page, product_id, max_retries, retry_delay):
        for attempt in range(max_retries + 1):
            try:
                if attempt > 0:
                    logging.info(f"    -> [ID: {product_id}] 第 {attempt + 1}/{max_retries + 1} 次重试，刷新页面...")
                    await page.reload(wait_until="domcontentloaded", timeout=60000)
                await page.locator(".okee-lp-Table-Header").wait_for(state="visible", timeout=60000)
                input_field = page.get_by_role("textbox", name="商品名称/ID")
                await input_field.fill("", timeout=15000)
                await input_field.fill(str(product_id), timeout=15000)
                async with page.expect_response(lambda response: "/api/life/service/mall/merchant/commission/product/list" in response.url, timeout=60000) as response_info:
                    await page.get_by_test_id("查询").click(force=True, timeout=15000)
                response = await response_info.value
                if not response.ok:
                    raise Exception(f"API request failed with status {response.status}")
                result_row = page.locator(f".okee-lp-Table-Row:has-text('{str(product_id)}')").first
                await result_row.wait_for(state="visible", timeout=30000)
                commission_status_locator = result_row.locator(".okee-lp-tag")
                await expect(commission_status_locator).to_be_visible(timeout=10000)
                status_text = (await commission_status_locator.text_content() or "").strip()
                status_result = "已设置" if status_text == "已设置" else f"未设置 ({status_text})"
                commission_info = "未找到"
                if status_result == "已设置":
                    channel_info_locator = result_row.locator("div:has-text('%')")
                    try:
                       await expect(channel_info_locator).to_be_visible(timeout=5000)
                       commission_info = (await channel_info_locator.text_content() or "").strip().replace('"', '')
                    except Exception:
                       logging.warning(f"    ! [ID: {product_id}] 状态为'已设置'但未找到佣金渠道文本。")
                       commission_info = "已设置但无详细比例"
                return status_result, commission_info
            except Exception as e:
                error_msg_line = str(e).splitlines()[0]
                logging.warning(f"    ! [ID: {product_id}] 在第 {attempt + 1} 次尝试中发生错误: {error_msg_line}")
                try:
                    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    screenshot_path = os.path.join(DEBUG_DIR, f"error_screenshot_{product_id}_attempt{attempt+1}_{timestamp}.png")
                    await page.screenshot(path=screenshot_path, full_page=True)
                    logging.info(f"      截图已保存至: {screenshot_path}")
                except Exception as screenshot_error:
                    logging.error(f"      尝试保存错误截图失败: {screenshot_error}")
                if attempt >= max_retries:
                    logging.error(f"    !! [ID: {product_id}] 所有重试均失败。")
                    return "查询失败", f"多次重试失败: {error_msg_line}"
                else:
                    await asyncio.sleep(retry_delay)
        return "查询失败", "未知错误"
    
    async def task_get_commission(self):
        logging.info("=====================================================")
        logging.info("========== 开始执行步骤3: 查询并回写佣金 (文件登录模式) ==========")
        logging.info("=====================================================")
        if not self._init_feishu_client(): return
        tasks_to_process = await self._get_empty_commission_records_from_feishu()
        if tasks_to_process is None:
            logging.error("从飞书获取待处理记录失败。")
            return
        if not tasks_to_process:
            logging.info("未在飞书中找到需要处理的记录。")
            return
        logging.info(f"共从飞书获取到 {len(tasks_to_process)} 条待处理记录。")
        browser = None
        page = None
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                logging.info(f"正在从文件 '{COOKIE_FILE}' 加载登录状态...")
                if not os.path.exists(COOKIE_FILE):
                    raise FileNotFoundError(f"Cookie文件 '{COOKIE_FILE}' 未找到。请确保该文件与脚本在同一目录下。")
                context = await browser.new_context(storage_state=COOKIE_FILE)
                logging.info(f"成功从 '{COOKIE_FILE}' 加载登录状态。")
                page = await context.new_page()
                logging.info("验证登录状态：导航到数据中心页面...")
                await page.goto("https://www.life-partner.cn/data-center", timeout=60000, wait_until="domcontentloaded")
                
                # --- 核心修改：多阶段截图 ---
                logging.info("阶段1: 导航完成，立即截图...")
                await page.screenshot(path=os.path.join(DEBUG_DIR, "01_after_goto.png"), full_page=True)
                logging.info("阶段1截图完成。等待5秒...")
                
                await asyncio.sleep(5)
                
                logging.info("阶段2: 等待5秒后，再次截图...")
                await page.screenshot(path=os.path.join(DEBUG_DIR, "02_after_5_seconds.png"), full_page=True)
                logging.info("阶段2截图完成。")
                # --- 多阶段截图结束 ---

                logging.info("现在开始验证页面内容...")
                await expect(page.get_by_text("数据看板", exact=True)).to_be_visible(timeout=20000) # 缩短最终验证时间
                logging.info("登录验证成功！页面上已找到'数据看板'。")

                base_url = f"https://www.life-partner.cn/vmok/order-detail?from_page=order_management&merchantId={self.configs['douyin_account_id']}&orderId=7494097018429261839&queryScene=0&skuOrderId=1829003050957856&tabName=ChargeSetting"
                await page.goto(base_url, timeout=120000, wait_until="domcontentloaded")
                logging.info("已成功导航到佣金设置页面。")

                total_tasks = len(tasks_to_process)
                for i, task in enumerate(tasks_to_process):
                    logging.info(f"--- [进度 {i+1}/{total_tasks}] 处理ID: {task['id']} ---")
                    status, commission_info = await self._process_id_on_page(page, task['id'], self.configs.get("max_retries", 3), self.configs.get("retry_delay", 2))
                    if status == "已设置":
                        logging.info(f"  -> 查询到佣金: {commission_info}，回写飞书...")
                        success = await self._update_feishu_record(task['record_id'], commission_info)
                        logging.info(f"  -> 回写飞书 {'成功' if success else '失败'}")
                    else:
                        logging.info(f"  -> 未查询到佣金 ({status})，跳过。")
        
        except Exception as e:
            logging.error(f"步骤3主线程执行期间发生错误: {e}", exc_info=True)
            if page and not page.is_closed():
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                error_screenshot_path = os.path.join(DEBUG_DIR, f"main_task_error_{timestamp}.png")
                try:
                    await page.screenshot(path=error_screenshot_path, full_page=True)
                    logging.info(f"捕获到主任务错误的截图已保存至: {error_screenshot_path}")
                except Exception as screenshot_error:
                    logging.error(f"尝试捕获主任务错误截图失败: {screenshot_error}")
        finally:
            if browser:
                await browser.close()
            self.feishu_client = None
            logging.info("\n步骤3执行完毕。")

# ==============================================================================
# 程序主入口 (CLI Version)
# ==============================================================================
async def main():
    runner = CliRunner()
    await runner.task_sync_feishu_ids()
    await runner.task_get_commission()
    logging.info("所有任务执行完毕。")

if __name__ == "__main__":
    asyncio.run(main())
