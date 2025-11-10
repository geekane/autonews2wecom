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
SILICONFLOW_API_KEY = "sk-nexfkxivirurtdvbpzkjgjcyplorwkssfitcvnppeaclunbe"
FEISHU_APP_ID = "cli_a6672cae343ad00e"
FEISHU_APP_SECRET = "0J4SpfBMeIxJEOXDJMNbofMipRgwkMpV"
FEISHU_APP_TOKEN = "BJ2gbK1onahpjZsglTgcxo7Onif"
FEISHU_TABLE_ID = "tbliEUHB9iSxZuiY"

# ==============================================================================
# --- 基础配置 ---
# ==============================================================================
DOWNLOAD_DIR = "douyin_downloads"
# 更新 User-Agent 以匹配最新请求
BROWSER_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0'
BASE_URL = "https://www.douyin.com"

# ==============================================================================
# --- API 硬编码配置 (已根据您的新请求更新) ---
# ==============================================================================
load_dotenv()

# 新的URL模板，直接从您提供的有效请求中提取和改造
# 注意：我移除了 locate_item_id 参数，因为它通常只在第一次加载时需要，后续翻页不需要，去掉可以使模板更通用
NEW_URL_TEMPLATE = (
    "https://www.douyin.com/aweme/v1/web/aweme/post/?device_platform=webapp&aid=6383&channel=channel_pc_web"
    "&sec_user_id={sec_user_id}&max_cursor={max_cursor}&locate_query=false&show_live_replay_strategy=1"
    "&need_time_list=1&time_list_query=0&whale_cut_token=&cut_version=1&count=18&publish_video_strategy_type=2"
    "&from_user_page=1&update_version_code=170400&pc_client_type=1&pc_libra_divert=Windows&support_h265=0"
    "&support_dash=1&cpu_core_num=8&version_code=290100&version_name=29.1.0&cookie_enabled=true"
    "&screen_width=1920&screen_height=1080&browser_language=zh-CN&browser_platform=Win32&browser_name=Edge"
    "&browser_version=141.0.0.0&browser_online=true&engine_name=Blink&engine_version=141.0.0.0"
    "&os_name=Windows&os_version=10&device_memory=8&platform=PC&downlink=10&effective_type=4g"
    "&round_trip_time=50&webid=7565134208906085938&uifid=0e81ba593d64ebaca259bdbe302de8d7e55ac2e982f7412f10fbc5c77c64bb8b7ab94a15c3cbec228bbb7aec7e0b416b74ca33aa945c08e0598b27d5a85e5910e78a595e898839084b0d7b6c3a290efd93da9c8f680ca863cd1b86719610cba1a844786d5b3980fe6360434e606ae8debe125b530cb7b18b1d3354b11498aa951314e8099f76b79f28bcf5a9b3bb39a02c568d275cb5b0efc2824de980cd309e"
    "&verifyFp=verify_mh695h1k_UcFGaefx_qIVX_4u4m_9SjN_7h5mGPpcJulS&fp=verify_mh695h1k_UcFGaefx_qIVX_4u4m_9SjN_7h5mGPpcJulS"
    "&msToken=L6dVJ6JafprGcw7wSXUxP5FQAZplCVND2wyeHIzoCK-UnT8c0I6ahMFR38RkLjel70cwUogwe6Rv4iSzE0Om5SO-ppYTnQ-T2ERa5Sb_C9gH4wjeC-gubm617d8U1le74nXi-CYQqZWdB_MG6sh0366cBQMINITsQZFRtSyu_Gr-Wg%3D%3D"
    "&a_bogus=Q60RDwU7m25RFd%2FS8Knc9volgH2MNsuyLri%2FWxCTSxugOZeOPRN0FNbprootmEo%2FNWBhwq37FdllbDVcstUsZ9HkzmpfSOXbkUVCIWsoM1wfTtzQgH8sez4FowMx05Gqa%2FVUilg6%2FUtq6fxAhHQE%2Fd5ry%2FKe5b8BB1xWk2YbT9s610gAEZnePpSDOwTYUyAt"
)

API_CONFIG = {
    "headers": {
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7,zh-TW;q=0.6',
        'cache-control': 'no-cache',
        'pragma': 'no-cache',
        'priority': 'u=1, i',
        'referer': 'https://www.douyin.com/', # 会被动态替换
        'sec-ch-ua': '"Microsoft Edge";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': BROWSER_USER_AGENT,
        # 【重要】确保这里的Cookie是最新的！建议从浏览器开发者工具中复制最新的Cookie值到此处或.env文件
        'cookie': os.getenv("DOUYIN_COOKIE", "enter_pc_once=1; UIFID_TEMP=0e81ba593d64ebaca259bdbe302de8d7e55ac2e982f7412f10fbc5c77c64bb8b7ab94a15c3cbec228bbb7aec7e0b416b8cc6bb2223e74295107d18f484403b4952a22c7cc7662ef51003ee8de79c1347; s_v_web_id=verify_mh695h1k_UcFGaefx_qIVX_4u4m_9SjN_7h5mGPpcJulS; dy_swidth=1920; dy_sheight=1080; fpk1=U2FsdGVkX1+cmna7cJx29ugl6UaGYR5JsOt/eWozss/7yQn7OazPIYsyxa4z0e5hnIpd1EkFvaHfX9/xTCnGIQ==; fpk2=df46e1d3e7507fa3d6888a71a1894105; passport_csrf_token=61cbac7b43e2a4ceabd604262636a197; passport_csrf_token_default=61cbac7b43e2a4ceabd604262636a197; is_dash_user=1; UIFID=0e81ba593d64ebaca259bdbe302de8d7e55ac2e982f7412f10fbc5c77c64bb8b7ab94a15c3cbec228bbb7aec7e0b416b74ca33aa945c08e0598b27d5a85e5910e78a595e898839084b0d7b6c3a290efd93da9c8f680ca863cd1b86719610cba1a844786d5b3980fe6360434e606ae8debe125b530cb7b18b1d3354b11498aa951314e8099f76b79f28bcf5a9b3bb39a02c568d275cb5b0efc2824de980cd309e; bd_ticket_guard_client_web_domain=2; n_mh=qheQFbah7hHshwNE2PNtjdisyGC4FcUrNDEFrG1EbjY; __security_mc_1_s_sdk_cert_key=28e677d2-42eb-be72; __security_mc_1_s_sdk_crypt_sdk=e975ef6d-46f2-b0e2; __security_server_data_status=1; SelfTabRedDotControl=%5B%7B%22id%22%3A%227113860477604694023%22%2C%22u%22%3A100%2C%22c%22%3A0%7D%5D; SEARCH_RESULT_LIST_TYPE=%22single%22; passport_assist_user=CjwINVGkj_CSxqESeQ97lqFN7pdg2YLkUQrqheZ2thjVwQ2ndz5D7L5GlWu0DkWoelXflnOuuZ71lwJxLNAaSgo8AAAAAAAAAAAAAE-snuM4Hv9JRAWFO1c68mLinprT2ToeXBYegYorcvjCtfbVlJ9lnFyRoBXCt5lfY-QQELTSgA4Yia_WVCABIgEDeQq_iA%3D%3D; sid_guard=5154404a1a4f5404632193e80785f6f3%7C1762258188%7C5184000%7CSat%2C+03-Jan-2026+12%3A09%3A48+GMT; uid_tt=0f694ba8cbbeb6797a4353022bf61b0b; uid_tt_ss=0f694ba8cbbeb6797a4353022bf61b0b; sid_tt=5154404a1a4f5404632193e80785f6f3; sessionid=5154404a1a4f5404632193e80785f6f3; sessionid_ss=5154404a1a4f5404632193e80785f6f3; session_tlb_tag=sttt%7C18%7CUVRAShpPVARjIZPoB4X28_________-vUw4PL3hFdftODQo-WSgMD6ZynEgPpiaD8XYM0CP2wQw%3D; is_staff_user=false; sid_ucp_v1=1.0.0-KGE5NjQzMjM1MDEwYzg3ZjFkM2MzZThhOGY0ZTQ3MjIzNjk2ZmM2ZjEKHwibstH8mgIQjNqnyAYY7zEgDDDMjrDQBTgFQPsHSAQaAmxmIiA1MTU0NDA0YTFhNGY1NDA0NjMyMTkzZTgwNzg1ZjZmMw; ssid_ucp_v1=1.0.0-KGE5NjQzMjM1MDEwYzg3ZjFkM2MzZThhOGY0ZTQ3MjIzNjk2ZmM2ZjEKHwibstH8mgIQjNqnyAYY7zEgDDDMjrDQBTgFQPsHSAQaAmxmIiA1MTU0NDA0YTFhNGY1NDA0NjMyMTkzZTgwNzg1ZjZmMw; __security_mc_1_s_sdk_sign_data_key_web_protect=3fe2d643-485c-aafb; login_time=1762258190982; _bd_ticket_crypt_cookie=ae152212ed85b5469b1ae884c0230250; publish_badge_show_info=%220%2C0%2C0%2C1762258191799%22; WallpaperGuide=%7B%22showTime%22%3A1762614205003%2C%22closeTime%22%3A0%2C%22showCount%22%3A1%2C%22cursor1%22%3A8%2C%22cursor2%22%3A2%7D; download_guide=%223%2F20251108%2F0%22; strategyABtestKey=%221762659658.924%22; ttwid=1%7Caf8F-ThymNJurVkfCRU-WKwSaq6k9DmNIajsp-vyQ_s%7C1762659658%7C1ba47a0e342307d76e37d95f71ba1c86b8c6bbda922d0c2a5043403c8708bb71; douyin.com; device_web_cpu_core=8; device_web_memory_size=8; architecture=amd64; __ac_nonce=0691022820082c9db2c06; __ac_signature=_02B4Z6wo00f01vVithgAAIDBo6LvlqTjAxL1QrKAANRV2d; __druidClientInfo=JTdCJTIyY2xpZW50V2lkdGglMjIlM0E2MTAlMkMlMjJjbGllbnRIZWlnaHQlMjIlM0E5ODglMkMlMjJ3aWR0aCUyMiUzQTYxMCUyQyUyMmhlaWdodCUyMiUzQTk4OCUyQyUyMmRldmljZVBpeGVsUmF0aW8lMjIlM0EwLjg5OTk5OTk3NjE1ODE0MjElMkMlMjJ1c2VyQWdlbnQlMjIlM0ElMjJNb3ppbGxhJTJGNS4wJTIwKFdpbmRvd3MlMjBOVCUyMDEwLjAlM0IlMjBXaW42NCUzQiUyMHg2NCklMjBBcHBsZVdlYktpdCUyRjUzNy4zNiUyMChLSFRNTCUyQyUyMGxpa2UlMjBHZWNrbyklMjBDaHJvbWUlMkYxNDEuMC4wLjAlMjBTYWZhcmklMkY1MzcuMzYlMjBFZGclMkYxNDEuMC4wLjAlMjIlN0Q=; volume_info=%7B%22isUserMute%22%3Afalse%2C%22isMute%22%3Atrue%2C%22volume%22%3A0.5%7D; stream_recommend_feed_params=%22%7B%5C%22cookie_enabled%5C%22%3Atrue%2C%5C%22screen_width%5C%22%3A1920%2C%5C%22screen_height%5C%22%3A1080%2C%5C%22browser_online%5C%22%3Atrue%2C%5C%22cpu_core_num%5C%22%3A8%2C%5C%22device_memory%5C%22%3A8%2C%5C%22downlink%5C%22%3A10%2C%5C%22effective_type%5C%22%3A%5C%224g%5C%22%2C%5C%22round_trip_time%5C%22%3A50%7D%22; playRecommendGuideTagCount=4; totalRecommendGuideTagCount=4; gulu_source_res=eyJwX2luIjoiZjI1NzFkMzg0MDZkYWFhM2I1MGFkY2E0MjgxMDI4N2VmMDEwMDcxYjQzNTA2ZWJkY2RlOGYxZDZmMjYyZWQ0NCJ9; FOLLOW_LIVE_POINT_INFO=%22MS4wLjABAAAA91OhU6CY-3l9vrXp4zfWCJk9elYyGeXyduNh44_fhV8%2F1762704000000%2F0%2F0%2F1762666919002%22; FOLLOW_NUMBER_YELLOW_POINT_INFO=%22MS4wLjABAAAA91OhU6CY-3l9vrXp4zfWCJk9elYyGeXyduNh44_fhV8%2F1762704000000%2F0%2F1762666514094%2F0%22; bd_ticket_guard_client_data=eyJiZC10aWNrZXQtZ3VhcmQtdmVyc2lvbiI6MiwiYmQtdGlja2V0LWd1YXJkLWl0ZXJhdGlvbi12ZXJzaW9uIjoxLCJiZC10aWNrZXQtZ3VhcmQtcmVlLXB1YmxpYy1rZXkiOiJCS1NWYStMSG03UHkvNFBjMVpGdEVYcUpUekpRTGE1TTk5UWROeFloL05wcTByY1ZWRGpqVVNTUXprbk9kTXV0M0ErMTcvQUtUejFjd3kwUldQY3pjNW89IiwiYmQtdGlja2V0LWd1YXJkLXdlYi12ZXJzaW9uIjoyfQ%3D%3D; odin_tt=79b4ed02b8629f3a1f3964711b777f2004fe762aeb5f065bb8c6d919d6f6578a6ca93752e9e57a0ed7ebb22612fe73df; bd_ticket_guard_client_data_v2=eyJyZWVfcHVibGljX2tleSI6IkJLU1ZhK0xIbTdQeS80UGMxWkZ0RVhxSlR6SlFMYTVNOTlRZE54WWgvTnBxMHJjVlZEampVU1NRemtuT2RNdXQzQSsxNy9BS1R6MWN3eTBSV1BjemM1bz0iLCJ0c19zaWduIjoidHMuMi4yNjA5N2I5MTEyZmRkYjQ0NTA4YWY2NWQ2NTI2OWEyNGQwYzMwOWM0ZTU5M2NmNGM3MTQxMzNkYTU2MTIxN2M5YzRmYmU4N2QyMzE5Y2YwNTMxODYyNGNlZGExNDkxMWNhNDA2ZGVkYmViZWRkYjJlMzBmY2U4ZDRmYTAyNTc1ZCIsInJlcV9jb250ZW50Ijoic2VjX3RzIiwicmVxX3NpZ24iOiI4dXNUbnhJMHk0djc3bDlibWpsME1BL2Ntd1h5dWg1UFVyOWQyK1YrT0JVPSIsInNlY190cyI6IiN0YU11aS9RMWNTVTh5S3hpNUcwTzVWd1h6SUV1aGY4SXhRK3R0NmhQRzdyYjNwV1pyako5OWI5NUYwQWEifQ%3D%3D; IsDouyinActive=true; home_can_add_dy_2_desktop=%220%22; biz_trace_id=a20315a9; sdk_source_info=7e276470716a68645a606960273f276364697660272927676c715a6d6069756077273f2771777060272927666d776a68605a607d71606b766c6a6b5a7666776c7571273f275e58272927666a6b766a69605a696c6061273f27636469766027292762696a6764695a7364776c6467696076273f275e582729277672715a646971273f2763646976602729277f6b5a666475273f2763646976602729276d6a6e5a6b6a716c273f2763646976602729276c6b6f5a7f6367273f27636469766027292771273f2737313234333233333337333234272927676c715a75776a716a666a69273f2763646976602778; bit_env=TrNYJxtm5QkEQ2E7STy_DCbsy3frpMDy4DrE8R7GaDyfXTxDyYJ5cN0dsl2N4-dj3oYSKJ8OEuuNmrOEWtOmFVmYebtRW86o1EZRSCfxxK2bFOGXr9njXiTC3bcNUchwxIKMCSoB7i9_6EcelD-N73_VIOVTwyAJU5zLwfeNmF8gTZEaUQDCoMQpyWVJSBi01bDXZ8pK7EMqDO4dCmCTYUFEQeru4nOG-F_caSJPriwbkVcVBvJSrkRXSEfVOhl0Ryenn1wEqQUC2nmPbhZrY3HYPd3iSQllapX8GSC_Vv6UvTTtfDjCBFrlaYMdHJmHYdoWhDtbmNOyapI8hWkdyuRAuw4GnKD21cPxwXMfNQW_-qrbb9Yx5A_1MNj84fm5icxN1wZ4Ll0Y8Z677yQovqqKS-9n-mtgHxreaQIy-oL2hNMg4315Ejv2Iw-9U55ZfKSEQjt_kv9HPmYzptQU0Eu-VgOhcw-_n4hJYl1p__FOlcUa1yUc1o5FBYWZ0hmkRko25OGimak93lZ7VmhJi9nsiYCs1Iiaf8DZl8VgFVA%3D; passport_auth_mix_state=haui7wl16pvmzt43shk601u08evhf4x6ullae0o8epxuosd6")
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
        # 更严格地清理标题作为文件名，移除所有Windows非法字符和空白符
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
            print(f"解析JSON时出错: {e}. 响应内容: {response.text[:200]}...") # 打印部分响应内容帮助调试
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
                 # 在跳转后的URL中寻找 sec_user_id
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
        # 由于所有参数都已包含在模板中，我们只需简单格式化即可
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
            # 抖音策略调整，有时play_addr的url_list是空的，需要用play_addr_h264
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
    result = crawler.get_user_videos(homepage_url, max_videos=2)
    
    if "error" in result:
        log_message(log_list, f"❌ 扫描失败: {result['error']}")
        return
        
    total_videos = result.get("total_count", 0)
    videos = result.get("videos", [])
    author_name = result.get("user_info", {}).get("nickname", "未知作者")
    
    log_message(log_list, f"✅ 扫描结束！作者: {author_name}, 共找到 {total_videos} 个视频。")
    if total_videos == 0: return
        
    log_message(log_list, "➡️ 阶段2: 开始逐一处理视频...")
    all_results_for_feishu = []
    downloaded_sizes = set()
    
    for i, video_info in enumerate(videos):
        log_message(log_list, f"--- ({i+1}/{total_videos}) 开始处理: {video_info['title']} ---")
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
        log_message(log_list, f"--- ({i+1}/{total_videos}) 处理完成 ---")
    
    if all_results_for_feishu:
        log_message(log_list, "➡️ 阶段3: 开始批量写入飞书...")
        try:
            feishu_api.add_records_batch(FEISHU_APP_TOKEN, table_id, all_results_for_feishu)
            log_message(log_list, f"✅ 成功批量写入 {len(all_results_for_feishu)} 条记录到飞书！")
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
