import requests
import time
import json
import lark_oapi as lark
# 确保导入所有需要的类
from lark_oapi.api.bitable.v1 import *
from lark_oapi.api.auth.v3 import *

# =================================================================
# 1. 配置信息
# =================================================================
# --- 抖音配置 ---
DOUYIN_APP_ID = "awbeykzyos7kbidv"
DOUYIN_APP_SECRET = "4575440b156ecbe144284e4f69d284a2"
DOUYIN_ACCOUNT_ID = "7241078611527075855"

# --- 飞书配置 ---
FEISHU_APP_ID = "cli_a6672cae343ad00e"
FEISHU_APP_SECRET = "0J4SpfBMeIxJEOXDJMNbofMipRgwkMpV"
FEISHU_BITABLE_APP_TOKEN = "MslRbdwPca7P6qsqbqgcvpBGnRh"
FEISHU_BITABLE_TABLE_ID = "tbl6jUYvV6TXXOZ2"
TARGET_FIELD_NAME = "商品ID"

# =================================================================
# 2. API 调用函数
# =================================================================

### --- 抖音API函数 (无改动) ---
def get_douyin_token():
    print(">>> 正在获取抖音 access-token...")
    url = "https://open.douyin.com/oauth/client_token/"
    payload = {"grant_type": "client_credential", "client_key": DOUYIN_APP_ID, "client_secret": DOUYIN_APP_SECRET}
    try:
        response = requests.post(url, headers={'Content-Type': 'application/json'}, json=payload)
        response.raise_for_status()
        data = response.json()
        if data.get("data", {}).get("error_code") == 0:
            print("    -> 抖音 access-token 获取成功！")
            return data["data"]["access_token"]
    except Exception as e:
        print(f"    -> 抖音 access-token 获取失败: {e}")
    return None

def get_douyin_poi_list(douyin_token, account_id):
    print("\n>>> 正在从抖音获取所有门店POI列表...")
    poi_ids = []
    page = 1
    poi_url = "https://open.douyin.com/goodlife/v1/shop/poi/query/"
    while True:
        params = {'account_id': account_id, 'page': page, 'size': 50}
        try:
            response = requests.get(poi_url, headers={'Content-Type': 'application/json', 'access-token': douyin_token}, params=params)
            response.raise_for_status()
            data = response.json()
            if data.get("data", {}).get("error_code") == 0:
                pois = data["data"].get("pois", [])
                if not pois: break
                poi_ids.extend([p.get("poi", {}).get("poi_id") for p in pois if p.get("poi", {}).get("poi_id")])
                if len(pois) < 50: break
                page += 1
            else: return []
        except Exception: return []
    print(f"    -> 成功获取到 {len(poi_ids)} 个门店ID。")
    return poi_ids

def get_products_for_single_poi(douyin_token, account_id, poi_id):
    product_ids = set()
    cursor = None
    product_url = "https://open.douyin.com/goodlife/v1/goods/product/online/query/"
    while True:
        params = {'account_id': account_id, 'poi_ids': [poi_id], 'count': 50}
        if cursor: params['cursor'] = cursor
        try:
            response = requests.get(product_url, headers={'content-type': 'application/json', 'access-token': douyin_token}, params=params)
            data = response.json()
            if data.get("data", {}).get("error_code") == 0:
                products = data["data"].get("products", [])
                for p in products:
                    prod_info = p.get("product", {})
                    if prod_info.get("product_id"):
                        product_ids.add(prod_info["product_id"])
                if data["data"].get("has_more"):
                    cursor = data["data"].get("next_cursor")
                else: break
            else: break
        except Exception: break
    return product_ids

### --- 飞书API函数 (已修正分页逻辑) ---
def get_all_feishu_product_ids(feishu_client, app_token, table_id, field_name):
    """从飞书多维表格一次性获取所有已存在的商品ID作为基准 (已修正分页逻辑)"""
    print(f"\n>>> 正在从飞书多维表格 '{table_id}' 获取已有的 '{field_name}' 作为基准数据...")
    existing_ids = set()
    page_token = None
    while True:
        # ******** 核心修正：动态构建请求 ********
        # 1. 先构建不带 page_token 的基础请求
        req_builder = SearchAppTableRecordRequest.builder() \
            .app_token(app_token) \
            .table_id(table_id) \
            .page_size(500) \
            .request_body(SearchAppTableRecordRequestBody.builder()
                .field_names([field_name])
                .build())
        
        # 2. 如果 page_token 存在（即非首次请求），才将其添加到请求中
        if page_token:
            req_builder.page_token(page_token)
            
        request = req_builder.build()
            
        try:
            response = feishu_client.bitable.v1.app_table_record.search(request)
            if not response.success():
                raise Exception(f"查询飞书记录失败, code: {response.code}, msg: {response.msg}")
                
            items = response.data.items or []
            for item in items:
                field_data_list = item.fields.get(field_name)
                if isinstance(field_data_list, list) and field_data_list:
                    text_value = field_data_list[0].get('text')
                    if text_value:
                        existing_ids.add(text_value)
                        
            if response.data.has_more:
                page_token = response.data.page_token
            else:
                break
        except Exception as e:
            print(f"    -> 查询飞书记录时发生异常: {e}")
            break
            
    print(f"    -> 基准数据获取完毕，飞书侧现有 {len(existing_ids)} 个ID。")
    return existing_ids

def add_records_to_feishu(feishu_client, app_token, table_id, field_name, new_ids_chunk):
    """向飞书多维表格单次写入一批新记录"""
    if not new_ids_chunk: return True
    print(f"    -> 正在向飞书写入 {len(new_ids_chunk)} 条新记录...")
    records_to_create = [AppTableRecord.builder().fields({field_name: new_id}).build() for new_id in new_ids_chunk]
    request = BatchCreateAppTableRecordRequest.builder() \
        .app_token(app_token).table_id(table_id).request_body(BatchCreateAppTableRecordRequestBody.builder().records(records_to_create).build()).build()
    try:
        response = feishu_client.bitable.v1.app_table_record.batch_create(request)
        if not response.success():
            print(f"    -> 批次写入失败, code: {response.code}, msg: {response.msg}")
            return False
        else:
            print(f"    -> 批次写入成功！")
            return True
    except Exception as e:
        print(f"    -> 批次写入时发生异常: {e}")
        return False

# =================================================================
# 3. 主执行流程
# =================================================================
def main():
    douyin_token = get_douyin_token()
    if not douyin_token:
        print("\n获取抖音Token失败，任务中止。")
        return
        
    print("\n>>> 正在初始化飞书客户端 (SDK将自动管理Token)...")
    feishu_client = lark.Client.builder() \
        .app_id(FEISHU_APP_ID) \
        .app_secret(FEISHU_APP_SECRET) \
        .log_level(lark.LogLevel.INFO) \
        .build()
    print("    -> 飞书客户端初始化成功！")

    existing_feishu_ids = get_all_feishu_product_ids(feishu_client, FEISHU_BITABLE_APP_TOKEN, FEISHU_BITABLE_TABLE_ID, TARGET_FIELD_NAME)

    # 在 main 函数中
    all_poi_ids = get_douyin_poi_list(douyin_token, DOUYIN_ACCOUNT_ID)
    print(f"\n>>> [正式运行] 开始处理全部 {len(all_poi_ids)} 家门店的数据...") 
    print("="*60)
    
    total_new_ids_written = 0
    for i, poi_id in enumerate(all_poi_ids):
        print(f"-> 正在处理第 {i+1}/{len(all_poi_ids)} 个门店 (POI ID: {poi_id})")
        
        douyin_ids_for_this_poi = get_products_for_single_poi(douyin_token, DOUYIN_ACCOUNT_ID, poi_id)
        if not douyin_ids_for_this_poi:
            print("    -> 未找到商品或查询失败，跳过。")
            continue
        
        new_ids_to_add = douyin_ids_for_this_poi - existing_feishu_ids
        
        if not new_ids_to_add:
            print("    -> 所有商品ID均已存在于飞书，无需操作。")
        else:
            print(f"    -> 发现 {len(new_ids_to_add)} 个新ID，准备写入...")
            success = add_records_to_feishu(feishu_client, FEISHU_BITABLE_APP_TOKEN, FEISHU_BITABLE_TABLE_ID, TARGET_FIELD_NAME, list(new_ids_to_add))
            
            if success:
                existing_feishu_ids.update(new_ids_to_add)
                total_new_ids_written += len(new_ids_to_add)

    print("="*60)
    print(">>> 验证任务执行完毕 <<<")
    print(f"总计新增了 {total_new_ids_written} 条记录到飞书多维表格。")

if __name__ == "__main__":
    main()
