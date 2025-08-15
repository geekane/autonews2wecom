import requests
import json
import os
import logging
import sys

# --- 日志配置 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- 飞书配置 ---
FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID")
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET")
FEISHU_APP_TOKEN = "MslRbdwPca7P6qsqbqgcvpBGnRh"
FEISHU_TABLE_ID = "tbl6jUYvV6TXXOZ2"

# --- 抖音配置 (已按要求修改) ---
DOUYIN_APP_ID = os.environ.get("DOUYIN_APP_ID")
DOUYIN_APP_SECRET = os.environ.get("DOUYIN_APP_SECRET")
DOUYIN_ACCOUNT_ID = os.environ.get("DOUYIN_ACCOUNT_ID")

# --- 企业微信机器人配置 ---
WECOM_WEBHOOK_URL = os.environ.get("WECOM_WEBHOOK_URL")

# --- 监控阈值配置 ---
POI_THRESHOLD = 100

# --- 缓存字典 (用于存储Token) ---
token_cache = {}

def check_secrets():
    """检查所有必需的密钥是否已配置"""
    required_secrets = [
        "FEISHU_APP_ID", "FEISHU_APP_SECRET",
        "DOUYIN_APP_ID", "DOUYIN_APP_SECRET", "DOUYIN_ACCOUNT_ID", # <-- 已修改
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
            logging.error(f"获取飞书Token失败: {data.get('msg')}")
            return None
    except requests.exceptions.RequestException as e:
        logging.error(f"获取飞书Token时网络错误: {e}")
        return None

def get_douyin_client_token():
    """获取抖音 client_token"""
    if token_cache.get("douyin_token"):
        return token_cache["douyin_token"]
        
    url = "https://open.douyin.com/oauth/client_token/"
    # --- 核心修改：使用新的变量名 ---
    payload = {
        "grant_type": "client_credential",
        "client_key": DOUYIN_APP_ID, # <-- 已修改
        "client_secret": DOUYIN_APP_SECRET # <-- 已修改
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json().get("data", {})
        if data.get("error_code") == 0:
            token = data.get("access_token")
            token_cache["douyin_token"] = token
            logging.info("成功获取抖音 client_token。")
            return token
        else:
            logging.error(f"获取抖音Token失败: {data.get('description')}")
            return None
    except requests.exceptions.RequestException as e:
        logging.error(f"获取抖音Token时网络错误: {e}")
        return None

def get_monitored_products(feishu_token):
    """从飞书多维表格获取需要监控的商品ID列表"""
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{FEISHU_APP_TOKEN}/tables/{FEISHU_TABLE_ID}/records/search"
    headers = {"Authorization": f"Bearer {feishu_token}"}
    payload = {
        "filter": {
            "conjunction": "and",
            "conditions": [{
                "field_name": "是否监控",
                "operator": "is",
                "value": ["是"]
            }]
        }
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
        if data.get("code") == 0:
            items = data.get("data", {}).get("items", [])
            product_ids = [
                item['fields'].get('商品ID') for item in items if '商品ID' in item['fields']
            ]
            logging.info(f"从飞书获取到 {len(product_ids)} 个待监控的商品ID。")
            return product_ids
        else:
            logging.error(f"查询飞书记录失败: {data.get('msg')}")
            return []
    except requests.exceptions.RequestException as e:
        logging.error(f"查询飞书记录时网络错误: {e}")
        return []

def get_douyin_product_details(douyin_token, product_id):
    """根据商品ID查询抖音商品详情，并返回门店数量和商品名称"""
    url = "https://open.douyin.com/goodlife/v1/goods/product/online/get/"
    headers = {"access-token": douyin_token}
    params = {"account_id": DOUYIN_ACCOUNT_ID, "product_ids": product_id}
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        if data.get("BaseResp", {}).get("StatusCode") == 0:
            products = data.get("data", {}).get("product_onlines", [])
            if not products:
                return 0, "未找到商品"
            
            product_data = products[0].get("product", {})
            product_name = product_data.get("product_name", "未知商品名称")
            poi_list = product_data.get("pois", [])
            return len(poi_list), product_name
        else:
            error_msg = data.get("BaseResp", {}).get("StatusMessage", "未知抖音API错误")
            logging.warning(f"查询抖音商品ID {product_id} 失败: {error_msg}")
            return -1, "查询失败"
    except requests.exceptions.RequestException as e:
        logging.error(f"查询抖音商品ID {product_id} 时网络错误: {e}")
        return -1, "网络错误"

def send_wechat_notification(webhook_url, message):
    """发送企业微信机器人通知"""
    if not webhook_url:
        logging.warning("未配置有效的企业微信 Webhook URL，跳过发送通知。")
        return
    
    payload = {
        "msgtype": "text",
        "text": {
            "content": message,
            "mentioned_list": ["@all"]
        }
    }
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
    except requests.exceptions.RequestException as e:
        logging.error(f"发送企业微信通知时发生网络错误: {e}")
    except Exception as e: 
        logging.error(f"发送企业微信通知时发生未知异常: {e}", exc_info=True)

def main():
    """主执行函数"""
    check_secrets()
    
    feishu_token = get_feishu_tenant_access_token()
    if not feishu_token:
        sys.exit(1)
        
    product_ids_to_monitor = get_monitored_products(feishu_token)
    if not product_ids_to_monitor:
        logging.info("没有需要监控的商品，任务结束。")
        return

    douyin_token = get_douyin_client_token()
    if not douyin_token:
        sys.exit(1)

    alert_messages = []
    for pid in product_ids_to_monitor:
        logging.info(f"正在检查商品ID: {pid}...")
        poi_count, product_name = get_douyin_product_details(douyin_token, pid)
        
        if poi_count == -1:
            message = (
                f"🚨 查询失败: 商品 `{product_name}` (ID: {pid})\n"
                f"- 原因: {product_name}"
            )
            alert_messages.append(message)
            continue

        logging.info(f"商品 '{product_name}' (ID: {pid}) 当前关联门店数量: {poi_count}")
        
        if poi_count < POI_THRESHOLD:
            message = (
                f"🚨 门店数量预警: 商品 `{product_name}`\n"
                f"- ID: {pid}\n"
                f"- 当前数量: {poi_count} 家\n"
                f"- 预警阈值: < {POI_THRESHOLD} 家"
            )
            alert_messages.append(message)

    if alert_messages:
        full_message = "【抖音商品门店数量监控警报】\n\n" + "\n\n".join(alert_messages)
        send_wechat_notification(WECOM_WEBHOOK_URL, full_message)
    else:
        logging.info("所有受监控的商品门店数量均正常，无需报警。")

if __name__ == "__main__":
    main()
