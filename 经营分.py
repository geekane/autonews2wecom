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

def fetch_all_store_data(url, headers):
    """
    抓取所有门店的数据，动态处理分页。
    """
    all_items = []
    page_num = 1
    total_pages = 1 # 先假设只有1页
    
    logging.info("开始抓取门店数据...")
    
    while page_num <= total_pages:
        logging.info(f"--- 正在请求第 {page_num} / {total_pages if total_pages > 1 else '?'} 页 ---")
        payload = {
            "conds": { "operating_levels": [], "city_map": {}, "order_by": 0, "poi_relation": 0 },
            "page_info": { "page": page_num, "page_size": 50 } # 不需要发送 total_page 和 total_count
        }
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            # 从第一次请求中动态获取总页数
            if page_num == 1:
                page_info = data.get("data", {}).get("page_info", {})
                total_pages = page_info.get("total_page", 1)
                total_count = page_info.get("total_count", 0)
                if total_pages > 1:
                    logging.info(f"检测到总共有 {total_count} 条数据，{total_pages} 页。")

            items_on_this_page = data.get("data", {}).get("poi_ranking_list", [])
            
            if items_on_this_page:
                all_items.extend(items_on_this_page)
                logging.info(f"获取 {len(items_on_this_page)} 条数据。当前总计: {len(all_items)} 条。")
            else:
                logging.warning(f"第 {page_num} 页返回的数据列表为空，可能已到达末页。")
                break # 如果某页为空，提前结束循环

            page_num += 1
            time.sleep(1) # 礼貌性等待，避免请求过快

        except requests.exceptions.RequestException as e:
            logging.error(f"请求第 {page_num} 页时发生网络错误: {e}")
            if "401" in str(e) or "Unauthorized" in str(e):
                logging.error("收到 401 未授权错误，很可能是Cookie已失效！")
            break
        except Exception as e:
            logging.error(f"处理第 {page_num} 页时发生未知错误: {e}")
            break
            
    return all_items


def main():
    """主函数：抓取数据、保存CSV、分析并发送通知。"""
    
    # ==============================================================================
    # 1. 配置请求参数 (Cookie已更新)
    # ==============================================================================
    
    # !! 关键一步：已将您的 Cookie 替换到下方 !!
    my_cookie = 'passport_csrf_token=7a3519ce55a78ef22c5e356898550401; passport_csrf_token_default=7a3519ce55a78ef22c5e356898550401; is_hit_partitioned_cookie_canary=true; is_hit_partitioned_cookie_canary_ss=true; is_staff_user_ls=false; bd_ticket_guard_client_web_domain=2; enter_pc_once=1; UIFID_TEMP=5a9ddafc2df5b1d5b452c3de63aa171cea81dc4215a756cefc72ee80e24fb54c4fa747406f275a4aa81e286803de22d3ce583ec532a64146c553291e1b6c1aa8d2978a4dc5bf00ab71a4a5232aeca697; bd_ticket_guard_web_domain=3; n_mh=qheQFbah7hHshwNE2PNtjdisyGC4FcUrNDEFrG1EbjY; is_staff_user=false; __security_server_data_status=1; SelfTabRedDotControl=%5B%7B%22id%22%3A%227113860477604694023%22%2C%22u%22%3A100%2C%22c%22%3A0%7D%5D; sid_guard=a6ea5ba7bb9dc78aa1c33d41c8c68018%7C1758515699%7C5184000%7CFri%2C+21-Nov-2025+04%3A34%3A59+GMT; uid_tt=000cfb30c70105ce0a96fbf679186d0a; uid_tt_ss=000cfb30c70105ce0a96fbf679186d0a; sid_tt=a6ea5ba7bb9dc78aa1c33d41c8c68018; sessionid=a6ea5ba7bb9dc78aa1c33d41c8c68018; sessionid_ss=a6ea5ba7bb9dc78aa1c33d41c8c68018; sid_ucp_v1=1.0.0-KDI3ZDU5YTY2YmVkNGE5MDYzZWJjYWVkYTNlOGY3NzM1OWNkZmJhMGYKHwibstH8mgIQ86PDxgYY7zEgDDDMjrDQBTgHQPQHSAQaAmxxIiBhNmVhNWJhN2JiOWRjNzhhYTFjMzNkNDFjOGM2ODAxOA; ssid_ucp_v1=1.0.0-KDI3ZDU5YTY2YmVkNGE5MDYzZWJjYWVkYTNlOGY3NzM1OWNkZmJhMGYKHwibstH8mgIQ86PDxgYY7zEgDDDMjrDQBTgHQPQHSAQaAmxxIiBhNmVhNWJhN2JiOWRjNzhhYTFjMzNkNDFjOGM2ODAxOA; login_time=1758515699222; _bd_ticket_crypt_cookie=467218cb2e50b325243f6ac60dc09e3d; __live_version__=%221.1.4.472%22; live_use_vvc=%22false%22; SEARCH_RESULT_LIST_TYPE=%22single%22; __security_mc_1_s_sdk_crypt_sdk=226c872a-4440-8b5a; __security_mc_1_s_sdk_cert_key=b8d89ff1-4cc2-8254; __security_mc_1_s_sdk_sign_data_key_web_protect=74d1eb07-4e95-b28b; volume_info=%7B%22isUserMute%22%3Afalse%2C%22isMute%22%3Afalse%2C%22volume%22%3A0.663%7D; s_v_web_id=verify_mg31j9tm_1b55cf5e_170e_604e_53a5_757e71aa6344; session_tlb_tag=sttt%7C20%7Cpupbp7udx4qhwz1ByMaAGP________-rD7XUNkz9oX00emtilMXvR4z0A6p0ZKctXP5IKiT1R30%3D; bd_ticket_guard_client_data=eyJiZC10aWNrZXQtZ3VhcmQtdmVyc2lvbiI6MiwiYmQtdGlja2V0LWd1YXJkLWl0ZXJhdGlvbi12ZXJzaW9uIjoxLCJiZC10aWNrZXQtZ3VhcmQtcmVlLXB1YmxpYy1rZXkiOiJCSUsvQlpVWFhHc2l3ZVY2QTk0dUpKZVI1VEprMjRtc1krSUpiTVU4eVc3ei84dGhKVnpYbC9rK3BFY05ONGVhY2JVdWV3bDdzUy9zVStmOWk3QWRRODQ9IiwiYmQtdGlja2V0LWd1YXJkLXdlYi12ZXJzaW9uIjoyfQ%3D%3D; gfkadpd=299467,30208|299467,22075; bd_ticket_guard_server_data=eyJ0aWNrZXQiOiJoYXNoLndQb3pZQmZ4N0RSVUFTQ3VneElqdmVIZFNHZUtIbWFwdUxqZEY3cVlRUGs9IiwidHNfc2lnbiI6InRzLjIuNTcyODQzYWIxNTNjMDhjNDYwNDcwMmIwMTVmZTk1MTY0MDc2N2ZlMDczNjM2MzA2Zjg5NTI0NWQ4OWMyNzZiM2M0ZmJlODdkMjMxOWNmMDUzMTg2MjRjZWRhMTQ5MTFjYTQwNmRlZGJlYmVkZGIyZTMwZmNlOGQ0ZmEwMjU3NWQiLCJjbGllbnRfY2VydCI6InB1Yi5CSUsvQlpVWFhHc2l3ZVY2QTk0dUpKZVI1VEprMjRtc1krSUpiTVU4eVc3ei84dGhKVnpYbC9rK3BFY05ONGVhY2JVdWV3bDdzUy9zVStmOWk3QWRRODQ9IiwibG9nX2lkIjoiMjAyNTEwMTAxMzU5MTVBQThGMjkxQjQzMjZFNzc1QTQ5MyIsImNyZWF0ZV90aW1lIjoxNzYwMDc1OTU1fQ%3D%3D; sid_guard_ls=26ed8bc5158f5f1fa50bb0fa20b8806a%7C1760075955%7C5183625%7CTue%2C+09-Dec-2025+05%3A53%3A00+GMT; uid_tt_ls=72ea757cb6f1787696e7dec0e2b29b75; uid_tt_ss_ls=72ea757cb6f1787696e7dec0e2b29b75; sid_tt_ls=26ed8bc5158f5f1fa50bb0fa20b8806a; sessionid_ls=26ed8bc5158f5f1fa50bb0fa20b8806a; sessionid_ss_ls=26ed8bc5158f5f1fa50bb0fa20b8806a; session_tlb_tag_ls=sttt%7C16%7CJu2LxRWPXx-lC7D6ILiAav_________cRjn5oihvK1ABQJBxOAZWZugc8nuSfqZwN2yXXSk6BqQ%3D; sid_ucp_v1_ls=1.0.0-KDE1N2M4ZGQ3NGY4OWNhMjYwNTZkODZkN2ViNjUzY2RlYTMwMTE4ZTAKHAj-xLC9_cykAhCzwaLHBhjRwRIgDDgBQOsHSAQaAmxxIiAyNmVkOGJjNTE1OGY1ZjFmYTUwYmIwZmEyMGI4ODA2YQ; ssid_ucp_v1_ls=1.0.0-KDE1N2M4ZGQ3NGY4OWNhMjYwNTZkODZkN2ViNjUzY2RlYTMwMTE4ZTAKHAj-xLC9_cykAhCzwaLHBhjRwRIgDDgBQOsHSAQaAmxxIiAyNmVkOGJjNTE1OGY1ZjFmYTUwYmIwZmEyMGI4ODA2YQ; odin_tt=64323229a883cd7b3705335f65fc07b203884ba4eae4746d7cbb3973cb13bdd7f009941f6c0c197fb7910b0e8d48f842; csrf_session_id=36b04fd18b0e5ae3141c3453d4eabfb3; ttwid=1%7ChHtwITeD3mt3jjV3mVNx01_PGu22OGPh--BBEsYHwhw%7C1760148814%7C03b956c84fe933e04ce486aaf5eb1530e193e57994f8720fc8eebf70316e992f'
    
    # 企业微信 Webhook URL 建议从环境变量获取
    webhook_url = os.getenv('WECOM_WEBHOOK_URL')

    url = "https://life.douyin.com/napi/growth/xscore/v1/poi/list?root_life_account_id=7241078611527075855"
    headers = {
        'authority': 'life.douyin.com', 'accept': 'application/json, text/plain, */*', 'accept-language': 'zh-CN,zh;q=0.9',
        'content-type': 'application/json', 'origin': 'https://life.douyin.com',
        'referer': 'https://life.douyin.com/p/liteapp/xscore/chain?enter_method=home_page&groupid=1768205901316096',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36 Edg/139.0.0.0',
        'cookie': my_cookie
    }

    # ==============================================================================
    # 2. 抓取、保存、分析 
    # ==============================================================================
    
    all_items = fetch_all_store_data(url, headers)

    if not all_items:
        logging.error("未能抓取到任何门店数据，程序终止。")
        send_wechat_notification(webhook_url, "【抖音门店分数检查失败】\n未能抓取到任何门店数据，请检查Cookie是否失效或网络问题。")
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

    # 分析并发送通知
    stores_with_negative_change = []
    try:
        with open(output_filename, 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            next(reader) # 跳过表头
            for row in reader:
                try:
                    store_name = row[0]
                    # 分数变化值可能是浮点数，先转为 float 再转为 int
                    score_change = int(float(row[2]))
                    if score_change < 0:
                        stores_with_negative_change.append(f"- {store_name}: 分数下降 {abs(score_change)}")
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
        # 可以选择性地发送一条“一切正常”的通知
        # send_wechat_notification(webhook_url, "【抖音门店分数检查报告】\n\n所有门店分数均未出现下降，一切正常。")


if __name__ == "__main__":
    main()
