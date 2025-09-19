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
    my_cookie = 'passport_csrf_token=7a3519ce55a78ef22c5e356898550401; passport_csrf_token_default=7a3519ce55a78ef22c5e356898550401; sid_guard_ls=d7643aa0714739ad5e1b5457922b15a1%7C1758006705%7C5184002%7CSat%2C+15-Nov-2025+07%3A11%3A47+GMT; sid_guard_ls=d7643aa0714739ad5e1b5457922b15a1%7C1758006705%7C5184002%7CSat%2C+15-Nov-2025+07%3A11%3A47+GMT; is_hit_partitioned_cookie_canary=true; is_hit_partitioned_cookie_canary=true; uid_tt_ls=464763fbb2ec6943271810caf6f37b18; uid_tt_ls=464763fbb2ec6943271810caf6f37b18; uid_tt_ss_ls=464763fbb2ec6943271810caf6f37b18; uid_tt_ss_ls=464763fbb2ec6943271810caf6f37b18; is_hit_partitioned_cookie_canary_ss=true; is_hit_partitioned_cookie_canary_ss=true; sid_tt_ls=d7643aa0714739ad5e1b5457922b15a1; sid_tt_ls=d7643aa0714739ad5e1b5457922b15a1; sessionid_ls=d7643aa0714739ad5e1b5457922b15a1; sessionid_ls=d7643aa0714739ad5e1b5457922b15a1; sessionid_ss_ls=d7643aa0714739ad5e1b5457922b15a1; sessionid_ss_ls=d7643aa0714739ad5e1b5457922b15a1; session_tlb_tag_ls=sttt%7C12%7C12Q6oHFHOa1eG1RXkisVof_________5tR2NAxZw-8ucNu8TXMxiGVAXNH6Qws-kU1gAkMlbxB4%3D; session_tlb_tag_ls=sttt%7C12%7C12Q6oHFHOa1eG1RXkisVof_________5tR2NAxZw-8ucNu8TXMxiGVAXNH6Qws-kU1gAkMlbxB4%3D; is_staff_user_ls=false; is_staff_user_ls=false; sid_ucp_v1_ls=1.0.0-KDBlZDY3NmVmN2Y4Yjg5OGRiZWQyZjJhM2M4MGRkOGJkOGYwNzM3YWYKGAj-xLC9_cykAhCxm6TGBhjRwRI4AUDrBxoCbGYiIGQ3NjQzYWEwNzE0NzM5YWQ1ZTFiNTQ1NzkyMmIxNWEx; sid_ucp_v1_ls=1.0.0-KDBlZDY3NmVmN2Y4Yjg5OGRiZWQyZjJhM2M4MGRkOGJkOGYwNzM3YWYKGAj-xLC9_cykAhCxm6TGBhjRwRI4AUDrBxoCbGYiIGQ3NjQzYWEwNzE0NzM5YWQ1ZTFiNTQ1NzkyMmIxNWEx; ssid_ucp_v1_ls=1.0.0-KDBlZDY3NmVmN2Y4Yjg5OGRiZWQyZjJhM2M4MGRkOGJkOGYwNzM3YWYKGAj-xLC9_cykAhCxm6TGBhjRwRI4AUDrBxoCbGYiIGQ3NjQzYWEwNzE0NzM5YWQ1ZTFiNTQ1NzkyMmIxNWEx; ssid_ucp_v1_ls=1.0.0-KDBlZDY3NmVmN2Y4Yjg5OGRiZWQyZjJhM2M4MGRkOGJkOGYwNzM3YWYKGAj-xLC9_cykAhCxm6TGBhjRwRI4AUDrBxoCbGYiIGQ3NjQzYWEwNzE0NzM5YWQ1ZTFiNTQ1NzkyMmIxNWEx; bd_ticket_guard_client_web_domain=2; enter_pc_once=1; UIFID_TEMP=5a9ddafc2df5b1d5b452c3de63aa171cea81dc4215a756cefc72ee80e24fb54c4fa747406f275a4aa81e286803de22d3ce583ec532a64146c553291e1b6c1aa8d2978a4dc5bf00ab71a4a5232aeca697; strategyABtestKey=%221758164761.791%22; __security_mc_1_s_sdk_crypt_sdk=73a4f57f-49a7-9b46; odin_tt=931992ef5600dd50fcbff0700dc37c5b64c6a86e8c700493b7b661f952c8a5e6a8ab38929a13b4627abd247febe5997e86c6143af47d0ac1a9fe503c738caef81227ddd627b3784e9442bfdf6bf84488; download_guide=%221%2F20250918%2F0%22; stream_recommend_feed_params=%22%7B%5C%22cookie_enabled%5C%22%3Atrue%2C%5C%22screen_width%5C%22%3A1920%2C%5C%22screen_height%5C%22%3A1080%2C%5C%22browser_online%5C%22%3Atrue%2C%5C%22cpu_core_num%5C%22%3A12%2C%5C%22device_memory%5C%22%3A8%2C%5C%22downlink%5C%22%3A10%2C%5C%22effective_type%5C%22%3A%5C%224g%5C%22%2C%5C%22round_trip_time%5C%22%3A50%7D%22; volume_info=%7B%22isUserMute%22%3Afalse%2C%22isMute%22%3Afalse%2C%22volume%22%3A0.5%7D; bd_ticket_guard_client_data=eyJiZC10aWNrZXQtZ3VhcmQtdmVyc2lvbiI6MiwiYmQtdGlja2V0LWd1YXJkLWl0ZXJhdGlvbi12ZXJzaW9uIjoxLCJiZC10aWNrZXQtZ3VhcmQtcmVlLXB1YmxpYy1rZXkiOiJCSUsvQlpVWFhHc2l3ZVY2QTk0dUpKZVI1VEprMjRtc1krSUpiTVU4eVc3ei84dGhKVnpYbC9rK3BFY05ONGVhY2JVdWV3bDdzUy9zVStmOWk3QWRRODQ9IiwiYmQtdGlja2V0LWd1YXJkLXdlYi12ZXJzaW9uIjoyfQ%3D%3D; home_can_add_dy_2_desktop=%221%22; IsDouyinActive=false; gfkadpd=299467,30208|299467,22075; s_v_web_id=verify_mfq9ju1d_zFnKb4BK_OFIi_4iEp_8ILy_Q5ww1GWoaegU; csrf_session_id=1e2b470772303b1b95cc56c7fe4b9285; ttwid=1%7ChHtwITeD3mt3jjV3mVNx01_PGu22OGPh--BBEsYHwhw%7C1758267160%7C8d064f3427f83ec797d8ea75e573e203f7802866a645ffb5829e7ba31ae7eb71'
    
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
    # 2. 抓取、保存、分析 
    # ==============================================================================
    
    all_items = []
    total_pages = 16
    
    for page_num in range(1, total_pages + 1):
        logging.info(f"--- 正在请求第 {page_num} / {total_pages} 页 ---")
        payload = {
          "conds": { "operating_levels": [], "city_map": {}, "order_by": 0, "poi_relation": 0 },
          "page_info": { "page": page_num, "page_size": 50, "total_page": total_pages, "total_count": 776 }
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
