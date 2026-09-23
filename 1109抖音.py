import sys
import io
import json
import asyncio
import os
import re
import requests
import time
import argparse
import pandas as pd
import ffmpeg
from dotenv import load_dotenv
from datetime import datetime
import subprocess
from typing import Dict, Any, Optional, List
from urllib.parse import urlparse, parse_qs

# URL提取函数
def extract_douyin_url(input_text):
    douyin_pattern = r'https?://v\.douyin\.com/[A-Za-z0-9]+'
    match = re.search(douyin_pattern, input_text)
    if match:
        return match.group(0)
    else:
        return None

# -- 解决在不同环境下输出编码问题的代码 --
if hasattr(sys.stdout, 'buffer'):
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    except Exception as e:
        print(f"Warning: Failed to reconfigure stdout/stderr encoding: {e}")

# ==============================================================================
# --- 核心配置 ---
# ==============================================================================
SILICONFLOW_API_KEY = os.getenv("SILICONFLOW_API_KEY")
FEISHU_APP_ID = os.getenv("FEISHU_APP_ID")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET")
FEISHU_APP_TOKEN = os.getenv("FEISHU_APP_TOKEN")
FEISHU_TABLE_ID = os.getenv("FEISHU_TABLE_ID")

# 检查必要变量是否存在
if not all([SILICONFLOW_API_KEY, FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_APP_TOKEN, FEISHU_TABLE_ID]):
    print("错误: 缺失必要的环境变量配置，请检查 GitHub Secrets 设置。")

# ==============================================================================
# --- API 配置（基于最新 curl 全量对齐：包含独立域名、风控头与完整会话 Cookie）---
# ==============================================================================
load_dotenv()

# 基础浏览器 User-Agent
BROWSER_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36 Edg/153.0.0.0'

# 1. 最新 URL 模板（对齐 www-hj 域名与全新签名参数）
NEW_URL_TEMPLATE = (
    "https://www-hj.douyin.com/aweme/v1/web/aweme/post/?"
    "device_platform=webapp"
    "&aid=6383"
    "&channel=channel_pc_web"
    "&sec_user_id={sec_user_id}"
    "&max_cursor={max_cursor}"
    "&locate_item_id=7524995207487720763"
    "&locate_query=false"
    "&show_live_replay_strategy=1"
    "&need_time_list=0"
    "&time_list_query=0"
    "&whale_cut_token="
    "&cut_version=1"
    "&count=18"
    "&publish_video_strategy_type=2"
    "&from_user_page=1"
    "&update_version_code=170400"
    "&pc_client_type=1"
    "&pc_libra_divert=Windows"
    "&support_h265=0"
    "&support_dash=1"
    "&cpu_core_num=12"
    "&version_code=290100"
    "&version_name=29.1.0"
    "&cookie_enabled=true"
    "&screen_width=1920"
    "&screen_height=1080"
    "&browser_language=zh-CN"
    "&browser_platform=Win32"
    "&browser_name=Edge"
    "&browser_version=153.0.0.0"
    "&browser_online=true"
    "&engine_name=Blink"
    "&engine_version=153.0.0.0"
    "&os_name=Windows"
    "&os_version=10"
    "&device_memory=32"
    "&platform=PC"
    "&downlink=1.45"
    "&effective_type=3g"
    "&round_trip_time=450"
    "&webid=7687924326851266111"
    "&uifid=8a94356f87650fa0412c61e664858f589013fe72dff3760b5026535a4ef20fecfd74a49fbc4b4910fe525d6e59c7d1ed04ec3d996cba72cef3fc60d07f5ff6e4c7074d00374568e4985f86cd64d954cacc48479271b025dac4bfe65dca42764b67e536114a7d70e296019bfb89d03ed081b754120fc101808668db14b85d016025d4da52ab36bc9a27f3b6026228ceb6950228c69c0dbe37205402f552ab44c4"
    "&msToken=RtLi67NcZCU90row7KnmLi7ct0a4O_OE2R3-OvFpTDKobbVNIigUZPsISrUb_ZyuXxm21mFf-pcaekBwLiDMGMuWpFS34plxLztqgAXsA7CFMFDP18Vd6RTN3QGG4qBw_9KHdZlajQfJHn8OHLyAbzz3LDcyPy2XRDCRRBkslH_o5GIjT49-xw%3D%3D"
    "&a_bogus=dfsVgHt7mN%2FbPdFtmCveHAdUeu9ArsSyrPiKbrrPSxYkLhMTvRNysPSpGozEsVWW0bBwh9V77VUAYDncp4UkpeCpomZkSLTfMt599gfLgqNfTztsEqbFCugFowsN0b4q-AV7ilg60Uto6jVAhrdY%2FplJy%2FuFQcWBPpOSkMYbE9shZFgAg3n3PQtZxwiqjD%3D%3D"
    "&verifyFp=verify_mudh01t1_h07pN9qI_Tkwn_4m3J_B6Cs_NkzxVZZVmVB2"
    "&fp=verify_mudh01t1_h07pN9qI_Tkwn_4m3J_B6Cs_NkzxVZZVmVB2"
    "&timestamp=1790131221"
    "&x-secsdk-web-signature=36450b11240e76d5510bff300d2e404a"
)

# 2. 与当前抓包同会话的最新 Cookie（已配对 verifyFp 与 s_v_web_id）
NEW_COOKIE = (
    "s_v_web_id=verify_mudh01t1_h07pN9qI_Tkwn_4m3J_B6Cs_NkzxVZZVmVB2; "
    "passport_csrf_token=5c0076574bf79c59609a661d6630d319; "
    "passport_csrf_token_default=5c0076574bf79c59609a661d6630d319; "
    "enter_pc_once=1; "
    "UIFID_TEMP=8a94356f87650fa0412c61e664858f589013fe72dff3760b5026535a4ef20fec657241762453014ce48570a5e878094aa6becbb38fb55ac72585082c82326d704cd9c479f8dc113112d92aa51b3c14bb; "
    "is_support_rtm_web_ts=1; "
    "strategyABtestKey=%221790129696.427%22; "
    "is_dash_user=1; "
    "volume_info=%7B%22isUserMute%22%3Afalse%2C%22isMute%22%3Afalse%2C%22volume%22%3A0.5%7D; "
    "ttwid=1%7CR8ojIxy17ufBcgFO7YxUHGjFRpQO1g-pzO2tUah3lNs%7C1790129700%7C6bd6140e50994398f43e9a56922e00c0a37ca65e6fca00421718d5e6a1a47842; "
    "bd_ticket_guard_regenerate_keys_time=2026-09-23/10:15:00; "
    "bd_ticket_guard_client_web_domain=2; "
    "passport_assist_user=Cjw0P8GNsW0B7EYyuUC8X4d8Kai-7cVm5sigTQOZ7P1CFQrftgpqZ4BsTdo3E6dsbIb3BGb3XnaAADIMbdoaSgo8AAAAAAAAAAAAAFDvqUsrRmnOw_mguzxg2yBBg3VE9eulfLlnSudC5Z5wzX46zLxGxeqJC-VwaTFHlrYqEOWAnQ4Yia_WVCABIgEDXw9J1g%3D%3D; "
    "n_mh=qheQFbah7hHshwNE2PNtjdisyGC4FcUrNDEFrG1EbjY; "
    "sid_guard=656e76c91082efe121cf57b0380843d0%7C1790129754%7C5184000%7CSun%2C+22-Nov-2026+02%3A15%3A54+GMT; "
    "uid_tt=513bbb0a497f4d8d884bcec9f9994e98; "
    "uid_tt_ss=513bbb0a497f4d8d884bcec9f9994e98; "
    "sid_tt=656e76c91082efe121cf57b0380843d0; "
    "sessionid=656e76c91082efe121cf57b0380843d0; "
    "sessionid_ss=656e76c91082efe121cf57b0380843d0; "
    "session_tlb_tag=sttt%7C18%7CZW52yRCC7-Ehz1ewOAhD0P_________8UpXynfkqBjG5X7pKAGS0BUizIN5M1c1SHWCE_3LIbYE%3D; "
    "is_staff_user=false; "
    "has_biz_token=false; "
    "sid_ucp_v1=1.0.0-KGViM2M4M2MwMjk1ZGQ3NTczZWE1MTBmYWJjMzQ1Mzg0ZDcwMDI5YTUKHwibstH8mgIQ2uzM1QYY7zEgDDDMjrDQBTgHQPQHSAQaAmxmIiA2NTZlNzZjOTEwODJlZmUxMjFjZjU3YjAzODA4NDNkMA; "
    "ssid_ucp_v1=1.0.0-KGViM2M4M2MwMjk1ZGQ3NTczZWE1MTBmYWJjMzQ1Mzg0ZDcwMDI5YTUKHwibstH8mgIQ2uzM1QYY7zEgDDDMjrDQBTgHQPQHSAQaAmxmIiA2NTZlNzZjOTEwODJlZmUxMjFjZjU3YjAzODA4NDNkMA; "
    "is_dbsc=false; "
    "x_tt_token=00656e76c91082efe121cf57b0380843d003c10e56887ae5cdbb9fac1daff3c69ed6ac1e48afd3f687d6673c6e64f42a25cf8f4328ca353a3fb7b698d45ae5ab6d8023dcd2d814d6ccb59fa3bf8e967a2535f85bd6411c7609e6efaea57bb4be34e4b--0a490a20bb06d3047f158bdbbec5e24c6890ddc32404780c82fa78b887b6c99d464d57491220f04dfe3461fb2947b485f28e10a4fec0e016a05acd1ab9d94f116a71278e3db118f6b4d309-3.0.4; "
    "login_time=1790129754020; "
    "UIFID=8a94356f87650fa0412c61e664858f589013fe72dff3760b5026535a4ef20fecfd74a49fbc4b4910fe525d6e59c7d1ed04ec3d996cba72cef3fc60d07f5ff6e4c7074d00374568e4985f86cd64d954cacc48479271b025dac4bfe65dca42764b67e536114a7d70e296019bfb89d03ed081b754120fc101808668db14b85d016025d4da52ab36bc9a27f3b6026228ceb6950228c69c0dbe37205402f552ab44c4; "
    "SelfTabRedDotControl=%5B%7B%22id%22%3A%227113860477604694023%22%2C%22u%22%3A100%2C%22c%22%3A0%7D%5D; "
    "_bd_ticket_crypt_cookie=e98d3911e9c2d94c62ffef65c5e7fcbf; "
    "__security_mc_1_s_sdk_sign_data_key_web_protect=dbad48f6-4af7-bfc4; "
    "__security_mc_1_s_sdk_cert_key=9c0abeae-4ebd-b3c9; "
    "__security_mc_1_s_sdk_crypt_sdk=bb2e79ad-4a1b-b235; "
    "__security_server_data_status=1; "
    "PhoneResumeUidCacheV1=%7B%2275960178971%22%3A%7B%22time%22%3A1790129757314%2C%22noClick%22%3A1%7D%7D; "
    "FOLLOW_NUMBER_YELLOW_POINT_INFO=%22MS4wLjABAAAA91OhU6CY-3l9vrXp4zfWCJk9elYyGeXyduNh44_fhV8%2F1790179200000%2F0%2F1790130456480%2F0%22; "
    "download_guide=%223%2F20260923%2F0%22; "
    "FOLLOW_LIVE_POINT_INFO=%22MS4wLjABAAAA91OhU6CY-3l9vrXp4zfWCJk9elYyGeXyduNh44_fhV8%2F1790179200000%2F0%2F1790131206654%2F0%22; "
    "publish_badge_show_info=%220%2C0%2C0%2C1790131212338%22; "
    "biz_trace_id=80e44477; "
    "sdk_source_info=7e276470716a68645a606960273f276364697660272927676c715a6d6069756077273f2771777060272927666d776a68605a607d71606b766c6a6b5a7666776c7571273f275e58272927666a6b766a69605a696c6061273f27636469766027292762696a6764695a7364776c6467696076273f275e582729277672715a646971273f2763646976602729277f6b5a666475273f2763646976602729276d6a6e5a6b6a716c273f2763646976602729276c6b6f5a7f6367273f27636469766027292771273f27363433333437343634353c3234272927676c715a75776a716a666a69273f2763646976602778; "
    "bit_env=JcYoAd-O4ttoF90YRUbrwAXcR_BIz10lxA-_JTdt_KDhG40Upm1tay8DOBQTsstHCZcVsBNd-TmkY7DN56QFnzfJ35PGMvTKncUXrwH40CnX3cFf7D0_3CsKrESGt9VoE0OjvTgQJ2UZqyjGe6C2GiQ-Kxs_9dZdyH0e8MGRlhE-Q6N2kTa2p54uTfZ3STYkNhr0fz0jNIahTakKpLuU3Z-6amgHEn-2oYDn_MoaYjMP39wSz9-XT9Z-pD8J2GFTxaIOG_nIkzPlkvc1BGHx5zdpxF0EClstJvt57FRGy1By7t_t9em8RL0Ow2PWLpbp-U5yOYTquJU7mL57bIdEs8jleVurxBRiYp3RJIodcbLlzBBwsL7F3ycA_ozmjm-kZaWens37uiUVTXUf5kosgzAXUngHLEJVzPQiLtjpYqU0LIw0N23Wx0RHEe8enAK4ckI5h-MiXaxWbOkGJ3TJclxAO3Ft4ItFwJbYP9mMmU3l9Ml9zTHU5tzmf6RZNNZgINK0ktCDDpeNNPMgRJmVfbwN4RBNqxTzAt3goloFVa8%3D; "
    "gulu_source_res=eyJwX2luIjoiMDc0ZDJhYWYwZWQzZTE0NWNjYjZlZWVkZTcwNjUxMDVmOWE3Y2NlMzgwODZkODFmMDI3NzFlNmUxYzJiZjdlNSJ9; "
    "passport_auth_mix_state=3od491vq3doaypoj894kf24xipfnqr26; "
    "IsDouyinActive=true; "
    "home_can_add_dy_2_desktop=%220%22; "
    "stream_recommend_feed_params=%22%7B%5C%22cookie_enabled%5C%22%3Atrue%2C%5C%22screen_width%5C%22%3A1920%2C%5C%22screen_height%5C%22%3A1080%2C%5C%22browser_online%5C%22%3Atrue%2C%5C%22cpu_core_num%5C%22%3A12%2C%5C%22device_memory%5C%22%3A32%2C%5C%22downlink%5C%22%3A1.45%2C%5C%22effective_type%5C%22%3A%5C%223g%5C%22%2C%5C%22round_trip_time%5C%22%3A450%7D%22; "
    "odin_tt=54466c08f0c899749384e8c80fb9ef5e6d41f0163312a1127c22fe6188f4bc77eb940dc862faa4e784ecdf3d717927a9ae4d19462addd8a41533c3d496176a92; "
    "bd_ticket_guard_client_data=eyJiZC10aWNrZXQtZ3VhcmQtdmVyc2lvbiI6MiwiYmQtdGlja2V0LWd1YXJkLWl0ZXJhdGlvbi12ZXJzaW9uIjoxLCJiZC10aWNrZXQtZ3VhcmQtcmVlLXB1YmxpYy1rZXkiOiJCRm1wNUY5aGdnd2dmQ0h2cStuRStOQW5qdkJwMTZ4OUorZFdGU1g4VTFGY2dubHlQR3lBYlg5Tmt4dTFSOUxZa1NGN0dGeTdPN2hrZ1pnaWZYTmlNZHM9IiwiYmQtdGlja2V0LWd1YXJkLXdlYi12ZXJzaW9uIjoyfQ%3D%3D"
)

# 3. 全套对齐请求头（增加 origin, sec-fetch-site, uifid, x-secsdk-web-signature）
API_CONFIG = {
    "headers": {
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7,zh-TW;q=0.6',
        'cache-control': 'no-cache',
        'origin': 'https://www.douyin.com',
        'pragma': 'no-cache',
        'priority': 'u=1, i',
        'referer': 'https://www.douyin.com/',
        'sec-ch-ua': '"Microsoft Edge";v="153", "Not_A Brand";v="8", "Chromium";v="153"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-site',
        'uifid': '8a94356f87650fa0412c61e664858f589013fe72dff3760b5026535a4ef20fecfd74a49fbc4b4910fe525d6e59c7d1ed04ec3d996cba72cef3fc60d07f5ff6e4c7074d00374568e4985f86cd64d954cacc48479271b025dac4bfe65dca42764b67e536114a7d70e296019bfb89d03ed081b754120fc101808668db14b85d016025d4da52ab36bc9a27f3b6026228ceb6950228c69c0dbe37205402f552ab44c4',
        'user-agent': BROWSER_USER_AGENT,
        'x-secsdk-web-signature': '36450b11240e76d5510bff300d2e404a',
        'cookie': os.getenv("DOUYIN_COOKIE", NEW_COOKIE)
    },
    "url_template": NEW_URL_TEMPLATE
}

# --- 日志记录辅助函数 ---
def log_message(log_list, message):
    timestamp = datetime.now().strftime("%H:%M:%S")
    log_entry = f"[{timestamp}] {message}"
    print(log_entry, flush=True)
    if log_list is not None:
        log_list.append(log_entry)

# --- 依赖检查 ---
def check_dependencies(log_list_ref):
    try:
        log_message(log_list_ref, "正在检查 ffmpeg 是否已安装...")
        subprocess.run(["ffmpeg", "-version"], check=True, capture_output=True, text=True, timeout=60)
        log_message(log_list_ref, "✅ ffmpeg 已安装。")
        return True, "所有依赖已就绪。"
    except FileNotFoundError:
        error_msg = "❌ 错误: ffmpeg 未安装或未在系统路径中。请先安装 ffmpeg。"
        log_message(log_list_ref, error_msg)
        return False, error_msg
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        error_msg = f"❌ 检查 ffmpeg 时出错: {e}"
        log_message(log_list_ref, error_msg)
        return False, error_msg

# --- 模块一：飞书数据仓库管理员 ---
class FeishuAPI:
    def __init__(self, app_id, app_secret):
        self.app_id = app_id
        self.app_secret = app_secret
        self.access_token = None
        self.token_expires_at = 0

    def _get_tenant_access_token(self):
        if self.access_token and time.time() < self.token_expires_at:
            return self.access_token
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        headers = {"Content-Type": "application/json; charset=utf-8"}
        payload = {"app_id": self.app_id, "app_secret": self.app_secret}
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        if data.get("code") == 0:
            self.access_token = data["tenant_access_token"]
            self.token_expires_at = time.time() + data.get("expire", 7200) - 300
            return self.access_token
        else:
            raise Exception(f"获取飞书Token失败: {data.get('msg')}")

    def get_first_table_id(self, app_token):
        token = self._get_tenant_access_token()
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables"
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(url, headers=headers, timeout=60)
        response.raise_for_status()
        data = response.json()
        if data.get("code") == 0 and data["data"]["items"]:
            return data["data"]["items"][0]["table_id"]
        else:
            raise Exception(f"获取飞书数据表ID失败: {data.get('msg')}")

    def get_all_video_links(self, app_token: str, table_id: str) -> set:
        all_links = set()
        token = self._get_tenant_access_token()
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
        headers = {"Authorization": f"Bearer {token}"}
        
        page_token = ""
        while True:
            params = {"page_size": 500, "field_names": '["视频链接"]'}
            if page_token:
                params["page_token"] = page_token
            
            try:
                response = requests.get(url, headers=headers, params=params, timeout=60)
                response.raise_for_status()
                result = response.json()

                if result.get("code") != 0:
                    print(f"获取飞书记录时出错: {result.get('msg')}")
                    break
                
                data = result.get("data", {})
                items = data.get("items", [])
                for item in items:
                    fields = item.get("fields", {})
                    video_link_field = fields.get("视频链接")
                    if isinstance(video_link_field, list) and len(video_link_field) > 0:
                        link_obj = video_link_field[0]
                        if isinstance(link_obj, dict) and "link" in link_obj:
                            all_links.add(link_obj["link"])
                    elif isinstance(video_link_field, str) and video_link_field.startswith("http"):
                        all_links.add(video_link_field)

                if data.get("has_more"):
                    page_token = data.get("page_token")
                else:
                    break
            except Exception as e:
                print(f"请求飞书记录时发生异常: {e}")
                break
        
        return all_links

    def add_records_batch(self, app_token, table_id, records):
        token = self._get_tenant_access_token()
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
        payload = {"records": records}
        response = requests.post(url, headers=headers, json=payload, timeout=120)
        response.raise_for_status()
        result = response.json()
        if result.get("code") != 0:
            print(f"飞书API错误详情: {result}")
            raise Exception(f"批量写入飞书记录失败: {result.get('msg')}")
        return result

# --- 模块二：视频下载器 ---
def download_video(video_url, title, downloaded_sizes):
    try:
        safe_title = re.sub(r'[\\/*?:"<>|\r\n\t]', "", title).strip()
        if len(safe_title) > 60:
            safe_title = safe_title[:60]
        if not safe_title:
            safe_title = f"video_{int(time.time())}"
        final_file_path = os.path.join(DOWNLOAD_DIR, f"{safe_title}.mp4")
        if os.path.exists(final_file_path):
            return "Skipped_Title_Exists", final_file_path
        headers = {'User-Agent': BROWSER_USER_AGENT, 'Referer': 'https://www.douyin.com/'}
        temp_file_path = os.path.join(DOWNLOAD_DIR, f"temp_{int(time.time())}.mp4")
        with requests.get(video_url, headers=headers, stream=True, timeout=180) as r:
            r.raise_for_status()
            with open(temp_file_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        file_size = os.path.getsize(temp_file_path)
        if file_size in downloaded_sizes:
            os.remove(temp_file_path)
            return "Duplicate_Size", None
        os.rename(temp_file_path, final_file_path)
        downloaded_sizes.add(file_size)
        return "Success", final_file_path
    except requests.exceptions.RequestException as e:
        if 'temp_file_path' in locals() and os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        return f"Download_Request_Error: {e}", None
    except Exception as e:
        if 'temp_file_path' in locals() and os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        return f"Download_IO_Error: {e}", None

# --- 模块三：AI文案提取师 ---
def extract_audio(video_path):
    try:
        audio_path = video_path.replace(".mp4", ".mp3")
        if os.path.exists(audio_path): return "Skipped", audio_path
        ffmpeg.input(video_path).output(audio_path, acodec='libmp3lame', audio_bitrate='128k').run(overwrite_output=True, quiet=True)
        return "Success", audio_path
    except Exception as e: return f"FFmpeg_Error: {e}", None

def transcribe_audio(audio_path):
    if not SILICONFLOW_API_KEY or "xxx" in SILICONFLOW_API_KEY: return "No_API_Key", "错误：请在代码中填入你的SiliconFlow API Key！"
    try:
        url = "https://api.siliconflow.cn/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {SILICONFLOW_API_KEY}"}
        payload = {"model": "FunAudioLLM/SenseVoiceSmall", "response_format": "text"}
        with open(audio_path, "rb") as f:
            files = {"file": f}
            response = requests.post(url, data=payload, files=files, headers=headers, timeout=300)
        response.raise_for_status()
        return "Success", response.text
    except requests.exceptions.HTTPError as e: return f"API_HTTP_Error_{e.response.status_code}", f"AI接口错误: {e.response.text}"
    except Exception as e: return f"Unknown_API_Error", f"调用AI接口时发生未知错误: {e}"

# --- 模块四：抖音API爬虫 ---
class RequestHandler:
    def __init__(self):
        self.session = requests.Session()

    def make_request(self, url: str, headers: Dict) -> Optional[Dict]:
        try:
            response = self.session.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"请求API时出错: {e}")
            return None
        except json.JSONDecodeError as e:
            print(f"解析JSON时出错: {e}. 响应内容: {response.text[:200]}...")
            return None


class DouyinCrawler:
    def __init__(self):
        self.request_handler = RequestHandler()

    def get_user_videos(self, user_url: str, max_videos: int = 50) -> Dict[str, Any]:
        sec_user_id = self._extract_sec_user_id(user_url)
        if not sec_user_id:
            return {"error": "无法从主页URL中提取用户ID (sec_user_id)"}

        result = {"user_info": {}, "videos": []}
        max_cursor = "0"
        
        while len(result["videos"]) < max_videos:
            request_url = self._build_request_url(sec_user_id, max_cursor)
            headers = API_CONFIG['headers'].copy()
            headers['referer'] = user_url

            response_data = self.request_handler.make_request(request_url, headers)

            if not response_data or response_data.get("status_code") != 0:
                error_msg = f"API请求失败或状态码不为0。数据: {response_data}"
                if not result["videos"]:
                    return {"error": error_msg}
                break
            
            aweme_list = response_data.get("aweme_list", [])
            if not aweme_list:
                break

            if not result["user_info"] and aweme_list[0].get("author"):
                result["user_info"] = self._parse_user_info(aweme_list[0]["author"])

            for aweme in aweme_list:
                if len(result["videos"]) >= max_videos:
                    break
                video_data = self._parse_single_video(aweme)
                if video_data and video_data.get('video_url'):
                    result["videos"].append(video_data)
            
            if not response_data.get("has_more", False):
                break
            max_cursor = str(response_data.get("max_cursor", ""))
            if not max_cursor:
                break
            time.sleep(1)

        result["total_count"] = len(result["videos"])
        return result

    def _extract_sec_user_id(self, user_url: str) -> Optional[str]:
        try:
            if 'sec_user_id=' in user_url:
                return parse_qs(urlparse(user_url).query).get('sec_user_id', [None])[0]
            
            if "v.douyin.com" in user_url:
                 response = requests.get(user_url, headers={"User-Agent": BROWSER_USER_AGENT}, timeout=10, allow_redirects=True)
                 response.raise_for_status()
                 final_url = response.url
                 if '/user/' in final_url:
                     match = re.search(r'/user/([a-zA-Z0-9_-]+)', final_url)
                     if match: return match.group(1)
                 return parse_qs(urlparse(final_url).query).get('sec_user_id', [None])[0]

            match = re.search(r'/user/([a-zA-Z0-9_-]+)', user_url)
            if match:
                return match.group(1)
            return None
        except Exception as e:
            print(f"提取 sec_user_id 时出错: {e}")
            return None

    def _build_request_url(self, sec_user_id, max_cursor):
        return API_CONFIG['url_template'].format(
            sec_user_id=sec_user_id,
            max_cursor=max_cursor
        )

    def _parse_user_info(self, author: Dict) -> Dict:
        return {"nickname": author.get("nickname", ""), "signature": author.get("signature", "")}

    def _parse_single_video(self, aweme: Dict) -> Optional[Dict]:
        try:
            title = aweme.get("desc", f"video_{aweme.get('aweme_id')}")
            video_info = aweme.get("video", {})
            play_addr = video_info.get("play_addr", {})
            if not play_addr.get("url_list"):
                play_addr = video_info.get("play_addr_h264", {})

            video_url = (play_addr.get("url_list") or [None])[0]
            if not video_url: return None

            return {
                "aweme_id": aweme.get("aweme_id"), "title": title, "desc": aweme.get("desc"),
                "create_time": aweme.get("create_time"), "author": aweme.get("author", {}).get("nickname"),
                "share_url": f"{BASE_URL}/video/{aweme.get('aweme_id')}", "video_url": video_url
            }
        except Exception:
            return None

# --- 模块五：总指挥 ---
async def process_homepage(homepage_url, log_list, feishu_api, table_id, crawler):
    log_message(log_list, f"➡️ 阶段1: 开始处理主页: {homepage_url}")
    result = crawler.get_user_videos(homepage_url, max_videos=4)
    
    if "error" in result:
        log_message(log_list, f"❌ 扫描失败: {result['error']}")
        return
        
    videos = result.get("videos", [])
    author_name = result.get("user_info", {}).get("nickname", "未知作者")
    
    log_message(log_list, f"✅ 扫描结束！作者: {author_name}, 共找到 {len(videos)} 个视频。")
    if not videos: return

    log_message(log_list, "➡️ 准备工作: 从飞书获取已存在的视频链接以进行去重...")
    try:
        existing_video_links = feishu_api.get_all_video_links(FEISHU_APP_TOKEN, table_id)
        log_message(log_list, f"✅ 已获取 {len(existing_video_links)} 个现有链接。")
    except Exception as e:
        log_message(log_list, f"⚠️ 警告: 无法从飞书获取现有链接，将继续处理所有视频。错误: {e}")
        existing_video_links = set()

    original_video_count = len(videos)
    videos_to_process = [
        v for v in videos
        if v.get('share_url') not in existing_video_links
    ]
    new_video_count = len(videos_to_process)
    log_message(log_list, f"🔍 筛选完成: {original_video_count} 个视频中，有 {new_video_count} 个是新的，需要处理。")
    
    if not videos_to_process:
        log_message(log_list, "✅ 无新视频需要处理，任务完成。")
        return
        
    log_message(log_list, "➡️ 阶段2: 开始逐一处理新视频...")
    all_results_for_feishu = []
    downloaded_sizes = set()
    
    for i, video_info in enumerate(videos_to_process):
        log_message(log_list, f"--- ({i+1}/{new_video_count}) 开始处理: {video_info['title']} ---")
        status, video_path = download_video(video_info['video_url'], video_info['title'], downloaded_sizes)
        if "Error" in status or status == "Duplicate_Size":
            log_message(log_list, f"  ⚠️  跳过下载: {status}")
            continue
        elif status == "Skipped_Title_Exists":
            log_message(log_list, f"  ✅ 文件已存在，直接使用: {video_path}")
        else:
            log_message(log_list, f"  ✅ 下载成功: {video_path}")
        
        status, audio_path = extract_audio(video_path)
        if "Error" in status:
            log_message(log_list, f"  ❌ 音频提取失败: {status}")
            continue
        elif status == "Skipped":
            log_message(log_list, "  ✅ 音频文件已存在，跳过提取")
        else:
            log_message(log_list, "  ✅ 音频提取成功")

        status, transcription = transcribe_audio(audio_path)
        if "Error" in status:
             log_message(log_list, f"  ❌ AI转写失败: {status} - {transcription}")
             transcription = f"AI转写失败: {status}"
        else:
             log_message(log_list, "  ✅ AI转写成功！")
        
        all_results_for_feishu.append({
            "fields": {
                "抖音名": author_name, "主页链接": homepage_url, "视频链接": video_info['share_url'],
                "视频文案": transcription, "发布日期": video_info['create_time'] * 1000
            }
        })
        log_message(log_list, f"--- ({i+1}/{new_video_count}) 处理完成 ---")
    
    if all_results_for_feishu:
        log_message(log_list, "➡️ 阶段3: 开始批量写入飞书...")
        try:
            feishu_api.add_records_batch(FEISHU_APP_TOKEN, table_id, all_results_for_feishu)
            log_message(log_list, f"✅ 成功批量写入 {len(all_results_for_feishu)} 条新记录到飞书！")
        except Exception as e:
            log_message(log_list, f"❌ 批量写入飞书失败: {e}")

# --- 添加从飞书API读取抖音主页链接的功能 ---
def get_homepage_links_from_feishu(feishu_api, app_token, table_id, log_list):
    log_message(log_list, "➡️ 开始从飞书获取主页链接...")
    try:
        token = feishu_api._get_tenant_access_token()
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/search"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
        payload = {"page_size": 500, "field_names": ["主页链接"]}
        all_links = []
        page_token = ""
        while True:
            if page_token: payload["page_token"] = page_token
            response = requests.post(url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            result = response.json()
            if result.get("code") != 0: raise Exception(f"获取飞书数据失败: {result.get('msg')}")
            data = result.get("data", {})
            items = data.get("items", [])
            for item in items:
                fields = item.get("fields", {})
                homepage_link_field = fields.get("主页链接")
                if isinstance(homepage_link_field, list) and len(homepage_link_field) > 0:
                    link_obj = homepage_link_field[0]
                    if isinstance(link_obj, dict) and "link" in link_obj: all_links.append(link_obj["link"])
                elif isinstance(homepage_link_field, str): all_links.append(homepage_link_field)
            page_token = data.get("page_token")
            if not data.get("has_more"): break
        log_message(log_list, f"✅ 成功获取 {len(all_links)} 个主页链接")
        return all_links
    except Exception as e:
        log_message(log_list, f"❌ 从飞书获取主页链接失败: {e}")
        return []

# --- 命令行主函数 ---
async def main():
    print("--- 程序开始执行 ---")
    parser = argparse.ArgumentParser(description='抖音AI内容中台 - 命令行版本')
    parser.add_argument('--mode', type=str, choices=['homepage', 'batch'], default='batch', help='运行模式: homepage(单个主页), batch(批量处理飞书中的主页)')
    parser.add_argument('--url', type=str, help='抖音主页链接')
    parser.add_argument('--source-table', type=str, default='tblsx7s2wqtxscvJ', help='包含主页链接的飞书表格ID')
    args = parser.parse_args()
    print(f"--- 参数解析完成: mode={args.mode} ---")
    
    log_list = []
    
    print("--- 步骤 0: 准备环境和依赖... ---")
    log_message(log_list, "➡️ 步骤 0: 正在准备环境和依赖...")
    success, message = check_dependencies(log_list)
    if not success: return
    log_message(log_list, f"✅ {message}")

    if not os.path.exists(DOWNLOAD_DIR): os.makedirs(DOWNLOAD_DIR)
    
    print("--- 初始化API... ---")
    try:
        feishu_api = FeishuAPI(FEISHU_APP_ID, FEISHU_APP_SECRET)
        target_table_id = FEISHU_TABLE_ID or feishu_api.get_first_table_id(FEISHU_APP_TOKEN)
        crawler = DouyinCrawler()
        log_message(log_list, f"✅ API初始化成功，将写入数据表: {target_table_id}")
    except Exception as e:
        log_message(log_list, f"❌ API初始化失败: {e}")
        return
    
    print(f"--- 进入 {args.mode} 模式 ---")
    if args.mode == 'homepage':
        if not args.url:
            log_message(log_list, "❌ 错误：主页处理模式需要提供 --url 参数")
            return
        await process_homepage(args.url, log_list, feishu_api, target_table_id, crawler)
    
    elif args.mode == 'batch':
        homepage_links = get_homepage_links_from_feishu(feishu_api, FEISHU_APP_TOKEN, args.source_table, log_list)
        if not homepage_links:
            log_message(log_list, "❌ 未从飞书中获取到任何主页链接")
            return
        
        for i, homepage_url in enumerate(homepage_links):
            await process_homepage(homepage_url, log_list, feishu_api, target_table_id, crawler)
            log_message(log_list, f"✅ ({i+1}/{len(homepage_links)}) 主页处理完成: {homepage_url}")

    print("\n--- 所有任务执行完毕 ---")

if __name__ == "__main__":
    asyncio.run(main())
