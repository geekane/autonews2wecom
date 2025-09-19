# -*- coding: utf-8 -*-
import requests
import json
import time
import csv
import os
import logging

# --- 配置日志记录 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def send_wechat_notification(webhook_url, message):
    """发送企业微信机器人通知。"""
    if not webhook_url:
        logging.warning("未配置有效的企业微信 Webhook URL，跳过发送通知。")
        return

    payload = { "msgtype": "text", "text": { "content": message, "mentioned_list": ["@all"] } }
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
    """主函数：抓取数据、保存CSV、分析并发送通知。"""
    
    # ==============================================================================
    # 1. 配置请求参数 (Cookie硬编码)
    # ==============================================================================
    
    # !! 关键一步：将下面的长字符串替换为您自己的、完整的、最新的有效Cookie !!
    my_cookie = 'PASTE_YOUR_VERY_LONG_COOKIE_STRING_HERE'
    
    # 企业微信 Webhook URL 仍然建议从环境变量获取，以方便在不同环境运行
    # 如果您也想硬编码，可以这样写: webhook_url = "你的webhook地址"
    webhook_url = os.getenv('WECOM_WEBHOOK_URL')

    if my_cookie == 'PASTE_YOUR_VERY_LONG_COOKIE_STRING_HERE':
        logging.critical("致命错误：请在代码中替换 my_cookie 的占位符为您自己的Cookie。")
        return

    url = "https://life.douyin.com/napi/growth/xscore/v1/poi/list?root_life_account_id=7241078611527075855"
    headers = {
        'authority': 'life.douyin.com', 'accept': 'application/json, text/plain, */*', 'accept-language': 'zh-CN,zh;q=0.9',
        'content-type': 'application/json', 'origin': 'https://life.douyin.com',
        'referer': 'https://life.douyin.com/p/liteapp/xscore/chain?enter_method=home_page&groupid=1768205901316096',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36 Edg/139.0.0.0',
        'cookie': my_cookie  # 使用硬编码的Cookie
    }

    # ==============================================================================
    # 2. 抓取、保存、分析 (此部分逻辑与之前完全相同)
    # ==============================================================================
    
    all_items = []
    total_pages = 78
    
    for page_num in range(1, total_pages + 1):
        logging.info(f"--- 正在请求第 {page_num} / {total_pages} 页 ---")
        payload = {
          "conds": { "operating_levels": [], "city_map": {}, "order_by": 0, "poi_relation": 0 },
          "page_info": { "page": page_num, "page_size": 10, "total_page": total_pages, "total_count": 776 }
        }
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=15)
            response.raise_for_status()
            data = response.json()
            items_on_this_page = data.get("data", {}).get("poi_ranking_list", [])
            
            if items_on_this_page:
                all_items.extend(items_on_this_page)
                logging.info(f"获取 {len(items_on_this_page)} 条数据。当前总计: {len(all_items)} 条。")
            else:
                logging.warning(f"第 {page_num} 页返回的数据列表为空。")
            time.sleep(1)
        except Exception as e:
            logging.error(f"请求第 {page_num} 页时发生错误: {e}")
            break

    if not all_items:
        logging.error("未能抓取到任何门店数据，程序终止。")
        send_wechat_notification(webhook_url, "【抖音门店分数检查失败】\n未能抓取到任何门店数据，请检查Cookie是否失效。")
        return
        
    output_filename = 'douyin_stores_scores.csv'
    csv_headers = ['门店名称', '当前得分', '较昨日分数变化']
    
    try:
        with open(output_filename, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(csv_headers)
            for item in all_items:
                poi_name = item.get('poi_name', '未知门店')
                total_score_info = item.get('total_score_info', {})
                current_score = total_score_info.get('obtain_score', 'N/A')
                yesterday_score_change = total_score_info.get('obtain_score_yesterday', 0)
                writer.writerow([poi_name, current_score, yesterday_score_change])
        logging.info(f"所有数据已成功保存到CSV文件: {output_filename}")
    except IOError as e:
        logging.error(f"保存CSV文件时发生错误: {e}")
        return

    stores_with_negative_change = []
    try:
        with open(output_filename, 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            next(reader)
            for row in reader:
                try:
                    store_name = row[0]
                    score_change = int(row[2])
                    if score_change < 0:
                        stores_with_negative_change.append(f"- {store_name}: {score_change}")
                except (IndexError, ValueError) as e:
                    logging.warning(f"处理行 {row} 时出错: {e}，已跳过。")
    except FileNotFoundError:
        logging.error(f"找不到CSV文件 {output_filename}，无法进行分析。")
        return

    if stores_with_negative_change:
        logging.warning(f"发现 {len(stores_with_negative_change)} 家门店分数下降。")
        message_content = "\n".join(stores_with_negative_change)
        final_message = f"【抖音门店分数下降提醒】\n\n以下门店分数较昨日出现下降：\n{message_content}\n\n请相关人员关注。"
        send_wechat_notification(webhook_url, final_message)
    else:
        logging.info("检查完成，所有门店分数无下降。")

if __name__ == "__main__":
    main()
