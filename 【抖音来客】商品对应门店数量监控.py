import requests
import json
import os
import logging
import sys
import pickle

# --- 日志配置 ---
logging.basicConfig(level=logging.INFO, stream=sys.stdout, format='%(asctime)s - %(levelname)s - %(message)s')

# --- 飞书配置 ---
FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID")
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET")
FEISHU_APP_TOKEN = "MslRbdwPca7P6qsqbqgcvpBGnRh"
FEISHU_TABLE_ID = "tbl6jUYvV6TXXOZ2"

# --- 抖音配置 ---
DOUYIN_APP_ID = os.environ.get("DOUYIN_APP_ID")
DOUYIN_APP_SECRET = os.environ.get("DOUYIN_APP_SECRET")
DOUYIN_ACCOUNT_ID = os.environ.get("DOUYIN_ACCOUNT_ID")

# --- 企业微信机器人配置 ---
WECOM_WEBHOOK_URL = os.environ.get("WECOM_WEBHOOK_URL")

# --- 监控阈值配置 ---
POI_THRESHOLD = 100

# --- 缓存文件路径 ---
CACHE_FILE = 'poi_count_cache.pkl'

# --- 全局Token缓存 ---
token_cache = {}

def check_secrets():
    """检查所有必需的密钥是否已配置"""
    required_secrets = [
        "FEISHU_APP_ID", "FEISHU_APP_SECRET",
        "DOUYIN_APP_ID", "DOUYIN_APP_SECRET", "DOUYIN_ACCOUNT_ID",
        "WECOM_WEBHOOK_URL"
    ]
    missing_secrets = [secret for secret in required_secrets if not globals()[secret]]
    if missing_secrets:
        logging.error(f"启动失败：缺少以下环境变量/密钥: {', '.join(missing_secrets)}")
        sys.exit(1)
    logging.info("所有密钥均已配置。")

def get_feishu_tenant_access_token():
    """获取飞书 tenant_access_token"""
    if token_cache.get("feishu_token"):
        return token_cache["feishu_token"]
    
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    payload = {"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET}
    
    logging.info("正在获取飞书 tenant_access_token...")
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("code") == 0:
            token = data.get("tenant_access_token")
            token_cache["feishu_token"] = token
            logging.info("成功获取飞书 tenant_access_token。")
            return token
        else:
            logging.error(f"获取飞书Token失败: code={data.get('code')}, msg={data.get('msg')}")
            return None
    except requests.exceptions.RequestException as e:
        logging.error(f"获取飞书Token时发生网络错误: {e}")
        return None
    except Exception as e:
        logging.error(f"获取飞书Token时发生未知异常: {e}", exc_info=True)
        return None

def get_douyin_client_token():
    """获取抖音 client_token"""
    if token_cache.get("douyin_token"):
        return token_cache["douyin_token"]
        
    url = "https://open.douyin.com/oauth/client_token/"
    payload = {
        "grant_type": "client_credential",
        "client_key": DOUYIN_APP_ID,
        "client_secret": DOUYIN_APP_SECRET
    }
    
    logging.info("正在获取抖音 client_token...")
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("data", {}).get("error_code") == 0:
            token = data.get("data", {}).get("access_token")
            token_cache["douyin_token"] = token
            logging.info("成功获取抖音 client_token。")
            return token
        else:
            logging.error(f"获取抖音Token失败: {data.get('data', {}).get('description')}")
            return None
    except requests.exceptions.RequestException as e:
        logging.error(f"获取抖音Token时发生网络错误: {e}")
        return None
    except Exception as e:
        logging.error(f"获取抖音Token时发生未知异常: {e}", exc_info=True)
        return None

def get_monitored_products(feishu_token):
    """从飞书多维表格获取需要监控的商品ID列表"""
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{FEISHU_APP_TOKEN}/tables/{FEISHU_TABLE_ID}/records/search"
    headers = {"Authorization": f"Bearer {feishu_token}"}
    payload = {
        "filter": {
            "conjunction": "and",
            "conditions": [{"field_name": "是否监控", "operator": "is", "value": ["是"]}]
        }
    }
    
    logging.info("正在从飞书查询待监控商品列表...")
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        if data.get("code") == 0:
            items = data.get("data", {}).get("items", [])
            product_ids = []
            for item in items:
                # --- 核心修改：正确解析飞书字段 ---
                product_id_field = item.get('fields', {}).get('商品ID')
                if isinstance(product_id_field, list) and len(product_id_field) > 0:
                    # 假设字段类型是数字或纯文本，它会返回一个列表，我们取第一个元素的text
                    product_id_str = product_id_field[0].get('text')
                    if product_id_str:
                        product_ids.append(product_id_str)
                elif isinstance(product_id_field, str): # 兼容纯文本字段
                    product_ids.append(product_id_field)
            
            logging.info(f"从飞书解析到 {len(product_ids)} 个待监控的商品ID: {product_ids}")
            return product_ids
        else:
            logging.error(f"查询飞书记录失败: code={data.get('code')}, msg={data.get('msg')}")
            return []
    except requests.exceptions.RequestException as e:
        logging.error(f"查询飞书记录时发生网络错误: {e}")
        return []
    except Exception as e:
        logging.error(f"解析飞书记录时发生未知异常: {e}", exc_info=True)
        return []

def get_douyin_product_details(douyin_token, product_id):
    """根据商品ID查询抖音商品详情，并返回门店数量和商品名称"""
    url = "https://open.douyin.com/goodlife/v1/goods/product/online/get/"
    headers = {"access-token": douyin_token}
    params = {"account_id": DOUYIN_ACCOUNT_ID, "product_ids": product_id}
    
    logging.info(f"正在查询抖音商品ID: {product_id}...")
    try:
        response = requests.get(url, headers=headers, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        if data.get("BaseResp", {}).get("StatusCode") == 0:
            products = data.get("data", {}).get("product_onlines", [])
            if not products:
                logging.warning(f"抖音API返回成功，但未找到商品ID {product_id} 的数据。")
                return 0, "未找到商品(可能已下架)"
            
            product_data = products[0].get("product", {})
            product_name = product_data.get("product_name", f"未知商品(ID:{product_id})")
            poi_list = product_data.get("pois", [])
            poi_count = len(poi_list)
            logging.info(f"商品 '{product_name}' (ID: {product_id}) 查询成功，门店数量: {poi_count}")
            return poi_count, product_name
        else:
            error_msg = data.get("BaseResp", {}).get("StatusMessage", "未知抖音API业务错误")
            logging.error(f"查询抖音商品ID {product_id} 失败: {error_msg}")
            return -1, "查询失败"
    except requests.exceptions.RequestException as e:
        logging.error(f"查询抖音商品ID {product_id} 时发生网络错误: {e}")
        return -1, "网络错误"
    except Exception as e:
        logging.error(f"处理抖音商品ID {product_id} 响应时发生未知异常: {e}", exc_info=True)
        return -1, "响应解析异常"

def send_wechat_notification(webhook_url, message):
    """发送企业微信机器人通知"""
    if not webhook_url:
        logging.warning("未配置企业微信 Webhook URL，跳过发送通知。")
        return
    
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
            logging.error(f"企业微信通知发送失败: {response_json.get('errmsg', '未知错误')}")
    except Exception as e:
        logging.error(f"发送企业微信通知时发生未知异常: {e}", exc_info=True)

def load_cache():
    """从文件加载上一次的门店数量缓存"""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'rb') as f:
                cache_data = pickle.load(f)
                logging.info(f"成功从 {CACHE_FILE} 加载缓存。")
                return cache_data
        except Exception as e:
            logging.warning(f"加载缓存文件 {CACHE_FILE} 失败: {e}，将使用空缓存。")
    else:
        logging.info("未找到缓存文件，将创建新的缓存。")
    return {}

def save_cache(data):
    """将当前的门店数量保存到缓存文件"""
    try:
        with open(CACHE_FILE, 'wb') as f:
            pickle.dump(data, f)
        logging.info(f"成功将当前门店数量保存到缓存文件 {CACHE_FILE}。")
    except Exception as e:
        logging.error(f"保存缓存到 {CACHE_FILE} 失败: {e}", exc_info=True)

def main():
    """主执行函数"""
    check_secrets()
    
    feishu_token = get_feishu_tenant_access_token()
    douyin_token = get_douyin_client_token()

    if not feishu_token or not douyin_token:
        logging.error("获取Token失败，无法继续执行任务。")
        sys.exit(1)
        
    product_ids_to_monitor = get_monitored_products(feishu_token)
    if not product_ids_to_monitor:
        logging.info("没有需要监控的商品，任务结束。")
        return

    previous_counts = load_cache()
    current_counts = {}
    alert_messages = []

    for pid in product_ids_to_monitor:
        poi_count, product_name = get_douyin_product_details(douyin_token, pid)
        
        # 只有成功获取到数据才进行处理和缓存
        if poi_count != -1:
            current_counts[pid] = poi_count
            previous_count = previous_counts.get(pid)
            
            # --- 核心报警逻辑修改 ---
            # 条件1: 当前数量低于阈值
            # 条件2: 上次数量不存在(首次监控) 或 上次数量不低于阈值(刚从正常变为异常)
            if poi_count < POI_THRESHOLD and (previous_count is None or previous_count >= POI_THRESHOLD):
                message = (
                    f"🚨 门店数量预警: 商品 `{product_name}`\n"
                    f"- ID: {pid}\n"
                    f"- 当前数量: {poi_count} 家 (首次低于阈值或首次监控)\n"
                    f"- 预警阈值: < {POI_THRESHOLD} 家"
                )
                alert_messages.append(message)
            elif poi_count < POI_THRESHOLD:
                 logging.info(f"商品 '{product_name}' (ID: {pid}) 门店数为 {poi_count}，已低于阈值但非首次触发，本次不重复报警。")
            else:
                 logging.info(f"商品 '{product_name}' (ID: {pid}) 门店数为 {poi_count}，数量正常。")

    if alert_messages:
        full_message = "【抖音商品门店数量监控警报】\n\n" + "\n\n".join(alert_messages)
        send_wechat_notification(WECOM_WEBHOOK_URL, full_message)
    else:
        logging.info("所有受监控的商品均无需报警。")

    # 无论是否报警，都保存本次的查询结果作为下次的对比基准
    save_cache(current_counts)

if __name__ == "__main__":
    main()
