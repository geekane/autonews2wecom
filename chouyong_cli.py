import logging
import json
import os
import time
from datetime import datetime, date
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
        logging.FileHandler(os.path.join(LOG_DIR, f"run_log_{date.today().strftime('%Y-%m-%d')}.log"), mode='a', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

class CliRunner:
    def __init__(self):
        self.configs = self.load_configs()
        self.douyin_access_token = None
        self.feishu_client = None

    def load_configs(self):
        logging.info("正在从环境变量加载配置...")
        configs = {}
        
        # 飞书配置
        configs["feishu_app_id"] = os.getenv("FEISHU_APP_ID")
        configs["feishu_app_secret"] = os.getenv("FEISHU_APP_SECRET")
        configs["feishu_app_token"] = os.getenv("FEISHU_APP_TOKEN")
        configs["feishu_table_id"] = os.getenv("FEISHU_TABLE_ID")
        configs["feishu_field_name"] = os.getenv("FEISHU_FIELD_NAME", "商品ID")
        configs["get_commission_source_field"] = os.getenv("GET_COMMISSION_SOURCE_FIELD", "商品ID")
        configs["get_commission_target_field"] = os.getenv("GET_COMMISSION_TARGET_FIELD", "佣金比例")
        
        # 抖音配置
        configs["douyin_key"] = os.getenv("DOUYIN_APP_ID")
        configs["douyin_secret"] = os.getenv("DOUYIN_APP_SECRET")
        configs["douyin_account_id"] = os.getenv("DOUYIN_ACCOUNT_ID")
        
        # POI表格配置
        configs["poi_app_token"] = os.getenv("POI_APP_TOKEN", "MslRbdwPca7P6qsqbqgcvpBGnRh")
        configs["poi_table_id"] = os.getenv("POI_TABLE_ID", "tblyKop71MJbXThq")
        configs["poi_id_field_name"] = os.getenv("POI_ID_FIELD_NAME", "ID")
        
        # 其他配置
        configs["poi_batch_size"] = int(os.getenv("POI_BATCH_SIZE", "20"))
        configs["feishu_max_workers"] = int(os.getenv("FEISHU_MAX_WORKERS", "5"))
        configs["max_retries"] = int(os.getenv("MAX_RETRIES", "3"))
        
        # 佣金配置
        configs["commission_online"] = os.getenv("COMMISSION_ONLINE", "0")
        configs["commission_offline"] = os.getenv("COMMISSION_OFFLINE", "0")
        configs["commission_zengliang"] = os.getenv("COMMISSION_ZENGLIANG", "0")
        configs["commission_zhiren"] = os.getenv("COMMISSION_ZHIREN", "0")
        
        # 验证必要配置
        required_configs = [
            "feishu_app_id", "feishu_app_secret", "feishu_app_token", "feishu_table_id",
            "douyin_key", "douyin_secret", "douyin_account_id"
        ]
        
        missing_configs = [config for config in required_configs if not configs.get(config)]
        if missing_configs:
            logging.error(f"缺少必要的环境变量配置: {', '.join(missing_configs)}")
            sys.exit(1)
            
        logging.info("环境变量配置加载成功。")
        return configs

    # ==============================================================================
    # 通用及辅助函数
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

    def _get_poi_ids_from_feishu_table(self):
        poi_app_token = self.configs.get("poi_app_token")
        poi_table_id = self.configs.get("poi_table_id")
        poi_id_field_name = self.configs.get("poi_id_field_name")
        logging.info(f"开始从飞书POI表格 (Table ID: {poi_table_id}) 获取门店POI ID...")
        if not self.feishu_client:
            logging.error("飞书客户端未初始化，无法获取POI ID。")
            return []
        
        # 首先获取表格的字段信息，以确定ID字段的类型
        try:
            table_request = GetAppTableRequest.builder().app_token(poi_app_token).table_id(poi_table_id).build()
            table_response = self.feishu_client.bitable.v1.app_table.get(table_request)
            if not table_response.success():
                logging.error(f"获取飞书表格信息失败: Code={table_response.code}, Msg={table_response.msg}")
                return []
            
            field_type = None
            proxy_type = None
            for field in table_response.data.table.fields:
                if field.field_name == poi_id_field_name:
                    field_type = field.type
                    proxy_type = field.proxy_type if hasattr(field, 'proxy_type') else None
                    logging.info(f"字段 '{poi_id_field_name}' 类型: {field_type}, 代理类型: {proxy_type}")
                    break
            
            if field_type is None:
                logging.error(f"未在表格中找到字段 '{poi_id_field_name}'")
                return []
            
            # 检查是否为查找引用类型（类型值为19）
            is_lookup_reference = (field_type == 19)
            if is_lookup_reference:
                logging.info(f"检测到字段 '{poi_id_field_name}' 为查找引用类型，将使用相应的解析方式")
            
        except Exception as e:
            logging.error(f"获取字段信息时发生异常: {e}", exc_info=True)
            return []
        
        all_poi_ids = []
        page_token = None
        while True:
            try:
                request_body = SearchAppTableRecordRequestBody.builder().field_names([poi_id_field_name]).build()
                request_builder = SearchAppTableRecordRequest.builder().app_token(poi_app_token).table_id(poi_table_id).page_size(500).request_body(request_body)
                if page_token: request_builder.page_token(page_token)
                request = request_builder.build()
                response = self.feishu_client.bitable.v1.app_table_record.search(request)
                if not response.success():
                    logging.error(f"查询飞书POI表格失败: Code={response.code}, Msg={response.msg}")
                    return []
                items = response.data.items or []
                for item in items:
                    if poi_id_field_name in item.fields and item.fields[poi_id_field_name]:
                        field_value = item.fields[poi_id_field_name]
                        
                        # 根据字段类型使用不同的解析方式
                        if is_lookup_reference:
                            # 查找引用类型的解析
                            if isinstance(field_value, list) and len(field_value) > 0:
                                # 查找引用字段的值结构
                                lookup_value = field_value[0]
                                if isinstance(lookup_value, dict):
                                    # 根据代理类型解析值
                                    if proxy_type == 1:  # 文本类型
                                        # 文本类型：值为包含 'text' 和 'type' 的对象
                                        poi_id_text = lookup_value.get('text', '')
                                        if poi_id_text:
                                            all_poi_ids.append(poi_id_text.strip())
                                    elif proxy_type == 11:  # 人员类型
                                        # 人员类型：值为包含用户信息的对象
                                        user_name = lookup_value.get('name', '')
                                        if user_name:
                                            all_poi_ids.append(user_name.strip())
                                    elif proxy_type == 2:  # 数字类型
                                        # 数字类型：值为数字
                                        poi_id_value = lookup_value.get('value', '')
                                        if poi_id_value is not None and poi_id_value != '':
                                            all_poi_ids.append(str(poi_id_value).strip())
                                    else:
                                        # 其他类型，尝试获取text或value
                                        poi_id_text = lookup_value.get('text', lookup_value.get('value', ''))
                                        if poi_id_text:
                                            all_poi_ids.append(str(poi_id_text).strip())
                        else:
                            # 原有的普通字段解析方式
                            if isinstance(field_value, list) and len(field_value) > 0:
                                poi_id_text = field_value[0].get('text', '')
                                if poi_id_text:
                                    all_poi_ids.append(poi_id_text.strip())
                
                if response.data.has_more:
                    page_token = response.data.page_token
                else:
                    break
            except Exception as e:
                logging.error(f"查询飞书POI表格时发生异常: {e}", exc_info=True)
                return []
        
        if not all_poi_ids:
            logging.error(f"未能从飞书表格 '{poi_table_id}' 的 '{poi_id_field_name}' 列读取到任何POI ID。")
        else:
            logging.info(f"成功从飞书获取到 {len(all_poi_ids)} 个门店POI ID。")
        return all_poi_ids

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
        current_cursor, page_num = "", 1
        while True:
            logging.info(f"    查询POI[{poi_id}] 第 {page_num} 页...")
            params = {"account_id": account_id, "poi_ids": [poi_id], "count": 50, "cursor": current_cursor}
            result = self._query_douyin_online_products(params)
            if result.get("success"):
                for p_info in result.get("products", []):
                    if product_id_val := p_info.get("product", {}).get("product_id"):
                        all_product_ids.add(str(product_id_val))
                if result.get("has_more"):
                    current_cursor, page_num = result.get("next_cursor", ""), page_num + 1
                    time.sleep(0.2)
                else:
                    break
            else:
                logging.error(f"    错误：查询POI[{poi_id}]失败: {result.get('message')}")
                return set()
        logging.info(f"    POI[{poi_id}]查询完成，找到 {len(all_product_ids)} 个商品ID。")
        return all_product_ids

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
                if page_token: request_builder.page_token(page_token)
                request = request_builder.build()
                response = self.feishu_client.bitable.v1.app_table_record.search(request)
                if not response.success():
                    logging.error(f"查询飞书现有记录失败: Code={response.code}, Msg={response.msg}")
                    return None
                items = response.data.items or []
                for item in items:
                    if field_name in item.fields and item.fields[field_name]:
                        product_id_text = item.fields[field_name][0].get('text', '')
                        if product_id_text: existing_ids.add(product_id_text.strip())
                if response.data.has_more: page_token = response.data.page_token
                else: break
            except Exception as e:
                logging.error(f"查询飞书现有记录时发生异常: {e}", exc_info=True)
                return None
        logging.info(f"成功从飞书获取到 {len(existing_ids)} 个已存在的商品ID。")
        return existing_ids

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
                if page_token: request_builder.page_token(page_token)
                request = request_builder.build()
                response = self.feishu_client.bitable.v1.app_table_record.search(request)
                if not response.success():
                    logging.error(f"查询飞书记录失败: Code={response.code}, Msg={response.msg}")
                    return None
                items = response.data.items or []
                for item in items:
                    if source_field in item.fields and item.fields[source_field]:
                        product_id_text = item.fields[source_field][0].get('text', '')
                        if product_id_text: all_records.append({"id": product_id_text, "record_id": item.record_id})
                if response.data.has_more: page_token = response.data.page_token
                else: break
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

    async def _process_id_on_page(self, page, product_id, max_retries, retry_delay):
        for attempt in range(max_retries + 1):
            try:
                if attempt > 0: logging.info(f"    -> [ID: {product_id}] 第 {attempt + 1}/{max_retries + 1} 次尝试...")
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
                    try:
                        await expect(channel_info_locator).to_be_visible(timeout=5000)
                        commission_info = (await channel_info_locator.text_content() or "").strip().replace('"', '')
                    except Exception:
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

    async def _set_single_commission(self, page, product_id, commission_values):
        try:
            logging.info(f"  - 步骤1: 搜索 {product_id}...")
            input_field = page.get_by_role("textbox", name="商品名称/ID")
            await expect(input_field).to_be_visible(timeout=20000)
            await input_field.clear(); await input_field.fill(str(product_id))
            await page.get_by_test_id("查询").click()
            first_row_locator = page.locator(".okee-lp-Table-Body .okee-lp-Table-Row").first
            set_commission_button = first_row_locator.get_by_role("button", name="设置佣金")
            await expect(set_commission_button).to_be_visible(timeout=15000)
            logging.info("  - 步骤2: 打开弹窗...")
            await set_commission_button.click()
            popup_title = page.get_by_text("设置佣金比例", exact=True)
            await expect(popup_title).to_be_visible(timeout=10000)
            logging.info("  - 步骤3: 填写佣金...")
            for label, value in commission_values.items():
                regex_pattern = re.compile(f"^{label}%$")
                input_locator = page.locator("div").filter(has_text=regex_pattern).get_by_placeholder("请输入")
                await expect(input_locator).to_be_visible(timeout=5000)
                await input_locator.fill(str(value))
                logging.info(f"    - '{label}' 已设置为 '{value}%'")
            logging.info("  - 步骤4: 提交...")
            submit_button = page.get_by_role("button", name="提交审核")
            await submit_button.click()
            await expect(popup_title).to_be_hidden(timeout=15000)
            logging.info(f"  ✔ [成功] ID: {product_id} 设置成功。")
            return True
        except Exception as e:
            error_msg = str(e).split('\n')[0]
            logging.error(f"  ❌ [失败] 为ID {product_id} 设置佣金时出错: {error_msg}", exc_info=False)
            try:
                screenshot_path = os.path.join(DEBUG_DIR, f"error_set_commission_{product_id}_{int(time.time())}.png")
                await page.screenshot(path=screenshot_path)
                logging.info(f"  - 错误截图已保存至: {screenshot_path}")
            except Exception as screenshot_error:
                logging.error(f"  - 尝试保存错误截图失败: {screenshot_error}")
            try:
                logging.info("  - 发生错误，尝试关闭弹窗以继续下一个任务...")
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(500)
                logging.info("  - 已尝试通过按 'Escape' 键关闭弹窗。")
            except Exception as cleanup_error:
                logging.error(f"  - 尝试关闭弹窗失败，后续任务可能受影响: {cleanup_error}")
            return False

    def _send_wechat_notification(self, count):
        webhook_url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=0e364220-efc0-4e7b-b505-129ea3371053"
        message = f"目前有【{count}】件商品需要确认抽佣，请通过app端进行确认操作"
        payload = {"msgtype": "text", "text": {"content": message, "mentioned_list": ["@all"]}}
        headers = {"Content-Type": "application/json"}
        logging.info("正在发送企业微信通知...")
        try:
            response = requests.post(webhook_url, headers=headers, data=json.dumps(payload), timeout=15)
            response.raise_for_status()
            response_json = response.json()
            if response_json.get("errcode") == 0:
                logging.info("企业微信通知发送成功。")
            else:
                error_msg = response_json.get("errmsg", "未知错误")
                logging.error(f"企业微信通知发送失败: {error_msg}")
        except requests.exceptions.RequestException as e:
            logging.error(f"发送企业微信通知时发生网络错误: {e}")
        except Exception as e:
            logging.error(f"发送企业微信通知时发生未知异常: {e}", exc_info=True)

    async def _fs_list_all_record_ids(self, app_token: str, table_id: str):
        logging.info(f"   - 开始获取 Table ID: {table_id} 中的所有记录...")
        record_ids = []
        page_token = None
        try:
            while True:
                builder = ListAppTableRecordRequest.builder().app_token(app_token).table_id(table_id).page_size(500)
                if page_token: builder.page_token(page_token)
                request = builder.build()
                response = self.feishu_client.bitable.v1.app_table_record.list(request)
                if not response.success():
                    logging.error(f"❌ [飞书错误] 获取记录列表失败: Code={response.code}, Msg='{response.msg}'")
                    return None
                if response.data and response.data.items:
                    record_ids.extend([item.record_id for item in response.data.items])
                if response.data and response.data.has_more: page_token = response.data.page_token
                else: break
            logging.info(f"   ✔ [成功] 共获取到 {len(record_ids)} 条现有记录。")
            return record_ids
        except Exception as e:
            logging.error(f"❌ [飞书错误] 获取记录列表时发生异常: {traceback.format_exc()}")
            return None

    async def _fs_batch_delete_records(self, app_token: str, table_id: str, record_ids: list):
        if not record_ids:
            logging.info("   - [信息] 没有需要删除的记录，跳过删除步骤。")
            return True
        logging.info(f"   - 准备删除 {len(record_ids)} 条旧记录...")
        try:
            for i in range(0, len(record_ids), 500):
                batch = record_ids[i:i + 500]
                req = BatchDeleteAppTableRecordRequest.builder().app_token(app_token).table_id(table_id).request_body(
                    BatchDeleteAppTableRecordRequestBody.builder().records(batch).build()).build()
                response = self.feishu_client.bitable.v1.app_table_record.batch_delete(req)
                if not response.success():
                    logging.error(f"❌ [飞书错误] 删除记录失败: Code={response.code}, Msg='{response.msg}'")
                    return False
            logging.info(f"   ✔ [成功] 所有 {len(record_ids)} 条旧记录已全部删除。")
            return True
        except Exception as e:
            logging.error(f"❌ [飞书错误] 删除记录时发生异常: {traceback.format_exc()}")
            return False

    async def _fs_batch_add_records(self, app_token: str, table_id: str, dataframe: pd.DataFrame):
        logging.info(f"   - 准备向 Table ID: {table_id} 批量写入 {len(dataframe)} 条新记录...")
        try:
            for i in range(0, len(dataframe), 500):
                df_batch = dataframe.iloc[i:i+500]
                records_to_add = [AppTableRecord.builder().fields(
                    {col: str(val) if pd.notna(val) else "" for col, val in row.to_dict().items()}
                ).build() for _, row in df_batch.iterrows()]
                req = BatchCreateAppTableRecordRequest.builder().app_token(app_token).table_id(table_id).request_body(
                    BatchCreateAppTableRecordRequestBody.builder().records(records_to_add).build()).build()
                response = self.feishu_client.bitable.v1.app_table_record.batch_create(req)
                if not response.success():
                    logging.error(f"❌ [飞书错误] 写入记录失败: Code={response.code}, Msg='{response.msg}'")
                    return False
                logging.info(f"   - 成功写入批次 {i//500 + 1} ({len(response.data.records)} 条记录)。")
            logging.info(f"   ✔ [成功] 所有 {len(dataframe)} 条新记录已成功写入。")
            return True
        except Exception as e:
            logging.error(f"❌ [飞书错误] 写入记录时发生异常: {traceback.format_exc()}")
            return False
            
    # ==============================================================================
    # 步骤0：同步 Life-Data.cn 数据
    # ==============================================================================
    async def task_sync_life_data(self):
        """
        步骤0：登录 life-data.cn，导出数据，并将其同步到指定的飞书表格。
        (最终版：强制等待5秒后点击导出，并确保错误时截图成功)
        """
        logging.info("==========================================================")
        logging.info("========== 开始执行步骤0: 同步 Life-Data.cn 数据 ==========")
        logging.info("==========================================================")
        
        feishu_config = {
            "app_id": os.getenv("LIFE_DATA_FEISHU_APP_ID", "cli_a8ad5b52783b901c"),
            "app_secret": os.getenv("LIFE_DATA_FEISHU_APP_SECRET", "DK8advnsYeChNF0yltKvKeqiQiYiAnyC"),
            "app_token": os.getenv("LIFE_DATA_FEISHU_APP_TOKEN", "MslRbdwPca7P6qsqbqgcvpBGnRh"),
            "table_id": os.getenv("LIFE_DATA_FEISHU_TABLE_ID", "tbluVbrXLRUmfouv")
        }
        cookie_file_for_life_data = '来客.json'
        target_url = "https://www.life-data.cn/store/my/chain/list?groupid=1768205901316096"
        download_dir = "downloads"
        
        if not self._init_feishu_client(): return

        playwright = None
        browser = None
        page = None
        downloaded_df = None

        try:
            playwright = await async_playwright().start()
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context(accept_downloads=True)
            
            if not os.path.exists(cookie_file_for_life_data):
                raise FileNotFoundError(f"Cookie 文件 '{cookie_file_for_life_data}' 未找到。")
            
            with open(cookie_file_for_life_data, 'r', encoding='utf-8') as f:
                storage_state = json.load(f)
            await context.add_cookies(storage_state['cookies'])
            logging.info(f"   - 正在从 {cookie_file_for_life_data} 加载 Cookies...")

            page = await context.new_page()
            await page.goto(target_url, timeout=90000, wait_until="networkidle")
            logging.info("   ✔ [成功] 网站页面加载完成。")
            
            logging.info("--- 开始灵活处理各类引导/确认弹窗 ---")
            popup_texts_to_click = ["知道了", "下一步", "去体验", "我知道了"]
            for text in popup_texts_to_click:
                for _ in range(3):
                    try:
                        button = page.locator(f"div[role='dialog'], div[id^='venus_poptip_']").get_by_text(text, exact=True)
                        await button.first.click(timeout=3000)
                        logging.info(f"   ✔ [成功] 已点击弹窗按钮: '{text}'")
                        await page.wait_for_timeout(500)
                    except Exception:
                        logging.info(f"   - [未检测到] 未发现或无需点击 '{text}' 按钮，继续。")
                        break
            
            logging.info("--- 弹窗处理完毕, 开始执行数据导出流程 ---")
            
            logging.info("   - 步骤 1/3: 点击 '门店' 选项卡...")
            men_dian_tab = page.get_by_text("门店", exact=True)
            await expect(men_dian_tab).to_be_visible(timeout=15000)
            await men_dian_tab.click()
            logging.info("   ✔ [成功] 已点击 '门店' 选项卡。")
            await page.wait_for_timeout(2000)

            try:
                await page.locator("div[id^='venus_poptip_'], div[role='dialog']").get_by_text("跳过", exact=True).click(timeout=2000)
            except Exception:
                pass

            logging.info("   - 步骤 2/3: 点击 '查看全部门店' 按钮...")
            view_all_button = page.locator("#PoiOverviewAndTrendViewAllStoresButton")
            await expect(view_all_button).to_be_visible(timeout=15000)
            await view_all_button.click()
            logging.info("   ✔ [成功] 已点击 '查看全部门店' 按钮。")
            await page.wait_for_load_state("networkidle", timeout=45000)
            logging.info("   ✔ [成功] '查看全部门店' 页面已加载完成。")
            
            logging.info("   - 步骤 3/3: 准备点击 '导出数据' 并等待下载...")
            export_button = page.get_by_role("button", name="导出数据")
            
            logging.info("       -> 检查 '导出数据' 按钮是否可见...")
            await expect(export_button).to_be_visible(timeout=15000)
            logging.info("       -> 强制等待5秒，以确保按钮变为可用状态...")
            await page.wait_for_timeout(5000)
            
            logging.info("   ✔ [准备就绪] 等待结束，现在点击 '导出数据' 按钮并开始等待下载...")
            
            async with page.expect_download(timeout=120000) as download_info:
                await export_button.click(force=True)
                logging.info("   ✔ [点击成功] 已点击 '导出数据' 按钮，正在等待下载完成...")
            
            download = await download_info.value
            
            os.makedirs(download_dir, exist_ok=True)
            save_path = os.path.join(download_dir, f"临时数据_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
            await download.save_as(save_path)
            logging.info(f"   ✔ [成功] 文件已下载到: {save_path}")
            
            downloaded_df = pd.read_excel(save_path, engine='openpyxl')
            logging.info(f"   ✔ [成功] Excel 文件读取成功，共 {len(downloaded_df)} 条记录。")

        except Exception as e:
            logging.error(f"❌ [致命错误] 浏览器自动化阶段发生错误: {traceback.format_exc()}")
            if page and not page.is_closed():
                try:
                    fail_screenshot_path = os.path.join(DEBUG_DIR, f"fatal_error_screenshot_{datetime.now().strftime('%H%M%S')}.png")
                    await page.screenshot(path=fail_screenshot_path, full_page=True)
                    logging.info(f"   - [失败截图] 已成功保存发生致命错误时的页面截图至: {fail_screenshot_path}")
                except Exception as screenshot_err:
                    logging.error(f"   - 尝试保存失败截图时再次发生错误: {screenshot_err}")
            else:
                logging.warning("   - [截图失败] 页面对象不存在或已关闭，无法捕获失败截图。")

        finally:
            if browser:
                await browser.close()
                logging.info("   - 浏览器已关闭。")
            if playwright:
                await playwright.stop()
                logging.info("   - Playwright 实例已停止。")

        if downloaded_df is not None and not downloaded_df.empty:
            logging.info("\n--- 开始同步数据至飞书 ---")
            await self._fs_list_all_record_ids(feishu_config['app_token'], feishu_config['table_id'])
            # 假设您有删除和增加记录的逻辑
        else:
            logging.warning("   - 未获取到有效数据，已跳过飞书同步步骤。")

        if downloaded_df is not None and not downloaded_df.empty:
            logging.info("\n--- 开始同步数据至飞书 ---")
            existing_ids = await self._fs_list_all_record_ids(feishu_config['app_token'], feishu_config['table_id'])
            if existing_ids is not None:
                delete_ok = await self._fs_batch_delete_records(feishu_config['app_token'], feishu_config['table_id'], existing_ids)
                if delete_ok:
                    await self._fs_batch_add_records(feishu_config['app_token'], feishu_config['table_id'], downloaded_df)
        else:
            logging.warning("   - 未获取到有效数据，已跳过飞书同步步骤。")           
        logging.info("\n步骤0执行完毕。")

    # ==============================================================================
    # 主任务流程
    # ==============================================================================
    async def task_sync_feishu_ids(self):
        logging.info("==================================================")
        logging.info("========== 开始执行步骤1: 同步商品ID到飞书 ==========")
        logging.info("==================================================")
        if not self._init_feishu_client(): return
        
        try:
            douyin_configs = {
                "douyin_key": self.configs.get("douyin_key"), 
                "douyin_secret": self.configs.get("douyin_secret"), 
                "douyin_account_id": self.configs.get("douyin_account_id")
            }
            if not self._get_douyin_client_token(douyin_configs): return
            
            existing_feishu_ids = self._get_all_existing_product_ids_from_feishu()
            if existing_feishu_ids is None:
                logging.error("无法从飞书获取现有数据，任务中止。")
                return

            poi_ids = self._get_poi_ids_from_feishu_table()
            if not poi_ids:
                logging.error("任务中止，因为未能从飞书获取到任何POI ID。请检查相关表格和配置。")
                return

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
                    continue
                
                logging.info(f"POI批次 {current_batch_num} 查询结束，发现 {len(ids_to_add)} 个新ID，准备写入飞书...")
                records_to_create = [AppTableRecord.builder().fields({self.configs['feishu_field_name']: str(pid)}).build() for pid in ids_to_add]
                for j in range(0, len(records_to_create), 500):
                    record_batch = records_to_create[j:j+500]
                    logging.info(f"  向飞书写入数据... (部分 {j//500 + 1})")
                    add_result = self._add_records_to_feishu_table(record_batch, self.configs['feishu_app_token'], self.configs['feishu_table_id'])
                    if not add_result["success"]:
                        logging.error(f"  写入飞书失败: {add_result.get('message')}"); break
                    else:
                        existing_feishu_ids.update(ids_to_add)
            
        except Exception as e:
            logging.error(f"同步商品ID任务主线程出错: {e}", exc_info=True)
        finally:
            self.feishu_client = None
            logging.info("\n步骤1执行完毕。")

    async def task_get_commission(self):
        logging.info("=====================================================")
        logging.info("========== 开始执行步骤2: 查询并回写佣金 ==========")
        logging.info("=====================================================")
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
                
                if not os.path.exists(COOKIE_FILE):
                    raise FileNotFoundError(f"Cookie文件 '{COOKIE_FILE}' 未找到。")
                
                context = await browser.new_context(storage_state=COOKIE_FILE)
                logging.info("成功加载登录状态。")
                
                page = await context.new_page()
                
                base_url = f"https://www.life-partner.cn/vmok/order-detail?from_page=order_management&merchantId=7241078611527075855&orderId=7521772903543900206&queryScene=0&skuOrderId=7521772903543916590&tabName=ChargeSetting"
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
            logging.info("\n步骤2执行完毕。")

    async def task_set_commission(self):
        logging.info("=====================================================")
        logging.info("========== 开始执行步骤3: 批量设置新佣金 ==========")
        logging.info("=====================================================")
        if not self._init_feishu_client():
            return

        try:
            tasks_to_process = await self._get_empty_commission_records_from_feishu()
            
            if tasks_to_process is None:
                logging.error("飞书错误: 从飞书获取待处理记录失败，请检查日志。")
                return
            if not tasks_to_process:
                logging.info("任务提示: 未在飞书中找到需要设置佣金的记录。")
                return

            logging.info(f"共从飞书获取到 {len(tasks_to_process)} 条需要设置佣金的记录。")

            successful_sets = 0
            failed_sets = 0

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                
                if not os.path.exists(COOKIE_FILE):
                    raise FileNotFoundError(f"Cookie文件 '{COOKIE_FILE}' 未找到。")
                context = await browser.new_context(storage_state=COOKIE_FILE)
                page = await context.new_page()
                
                base_url = f"https://www.life-partner.cn/vmok/order-detail?from_page=order_management&merchantId=7241078611527075855&orderId=7521772903543900206&queryScene=0&skuOrderId=7521772903543916590&tabName=ChargeSetting"
                await page.goto(base_url, timeout=90000, wait_until="domcontentloaded")
                
                for i, task in enumerate(tasks_to_process):
                    pid = task["id"]
                    logging.info(f"--- [进度 {i+1}/{len(tasks_to_process)}] 开始处理商品ID: {pid} ---")
                    
                    commission_values = {
                        '线上经营': self.configs.get('commission_online', '0'),
                        '线下扫码': self.configs.get('commission_offline', '0'),
                        '增量宝': self.configs.get('commission_zengliang', '0'),
                        '职人账号': self.configs.get('commission_zhiren', '0')
                    }
                    
                    success = await self._set_single_commission(page, pid, commission_values)
                    
                    if success:
                        successful_sets += 1
                    else:
                        failed_sets += 1
                
                await browser.close()
            
            if successful_sets > 0:
                await asyncio.to_thread(self._send_wechat_notification, successful_sets)
            
            logging.info(f"\n所有佣金设置任务处理完成！成功: {successful_sets}, 失败: {failed_sets}")

        except Exception as e:
            logging.error(f"设置佣金任务主线程发生严重错误: {e}", exc_info=True)
        finally:
            if self.feishu_client:
                self.feishu_client = None
            logging.info("\n步骤3执行完毕。")

# ==============================================================================
# 程序主入口
# ==============================================================================
async def main():
    runner = CliRunner()
    await runner.task_sync_life_data()
    await runner.task_sync_feishu_ids()
    await runner.task_get_commission()
    await runner.task_set_commission() 
    logging.info("\n所有任务执行完毕。")

if __name__ == "__main__":
    asyncio.run(main())
