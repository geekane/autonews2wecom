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
    # sys.exit(1) # 可选：如果缺失则停止运行

# ==============================================================================
# --- 基础配置 ---
# ==============================================================================
DOWNLOAD_DIR = "douyin_downloads"
# 更新 User-Agent 以匹配最新请求 (Chrome 141)
BROWSER_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0'
BASE_URL = "https://www.douyin.com"

# ==============================================================================
# --- API 硬编码配置 (已更新 Cookie) ---
# ==============================================================================
load_dotenv()

# 注意：如果后续依然报错，可能需要更新 URL 中的 msToken 和 a_bogus 参数，或者使用 Selenium 动态获取
NEW_URL_TEMPLATE = (
    "https://www.douyin.com/aweme/v1/web/aweme/post/?device_platform=webapp&aid=6383&channel=channel_pc_web"
    "&sec_user_id={sec_user_id}&max_cursor={max_cursor}&locate_query=false&show_live_replay_strategy=1"
    "&need_time_list=1&time_list_query=0&whale_cut_token=&cut_version=1&count=18&publish_video_strategy_type=2"
    "&from_user_page=1&update_version_code=170400&pc_client_type=1&pc_libra_divert=Windows&support_h265=0"
    "&support_dash=1&cpu_core_num=8&version_code=290100&version_name=29.1.0&cookie_enabled=true"
    "&screen_width=1920&screen_height=1080&browser_language=zh-CN&browser_platform=Win32&browser_name=Edge"
    "&browser_version=141.0.0.0&browser_online=true&engine_name=Blink&engine_version=141.0.0.0"
    "&os_name=Windows&os_version=10&device_memory=8&platform=PC&downlink=10&effective_type=4g"
    "&round_trip_time=50"
    # 这里通常建议留空或使用通用 token，具体能否通过取决于 Cookie 的有效性
    "&webid=7565134208906085938" 
    "&msToken=L6dVJ6JafprGcw7wSXUxP5FQAZplCVND2wyeHIzoCK-UnT8c0I6ahMFR38RkLjel70cwUogwe6Rv4iSzE0Om5SO-ppYTnQ-T2ERa5Sb_C9gH4wjeC-gubm617d8U1le74nXi-CYQqZWdB_MG6sh0366cBQMINITsQZFRtSyu_Gr-Wg%3D%3D"
    "&a_bogus=Q60RDwU7m25RFd%2FS8Knc9volgH2MNsuyLri%2FWxCTSxugOZeOPRN0FNbprootmEo%2FNWBhwq37FdllbDVcstUsZ9HkzmpfSOXbkUVCIWsoM1wfTtzQgH8sez4FowMx05Gqa%2FVUilg6%2FUtq6fxAhHQE%2Fd5ry%2FKe5b8BB1xWk2YbT9s610gAEZnePpSDOwTYUyAt"
)

# 你的新 Cookie 字符串
NEW_COOKIE = (
    "passport_csrf_token=069391dee2fd829e73e008ee873c2767; passport_csrf_token_default=069391dee2fd829e73e008ee873c2767; "
    "n_mh=-zEnurXnLSTX8GC60YFZZfobJ1QRe0_XD4hG0PZoero; "
    "odin_tt=1bace36a563833e09b070672f45e1b171985aaa5ab5ee36bb65fe73ccf751805d0461a3063868c177af5bf6301c125d1145dfed4bbbb705485845dd7da1edf03; "
    "passport_auth_mix_state=f71ptlpqcr37rk2c10jhrc6dl82yk5ar; "
    "s_v_web_id=verify_mp580p2u_OcN4AQ35_vIdz_4vqM_BG1c_xnENOkaUm3cH; "
    "playRecommendGuideTagCount=1; totalRecommendGuideTagCount=1; "
    "publish_badge_show_info=%220%2C0%2C0%2C1782114628832%22; "
    "SEARCH_RESULT_LIST_TYPE=%22single%22; "
    "SEARCH_UN_LOGIN_PV_CURR_DAY=%7B%22date%22%3A1778746981379%2C%22count%22%3A2%7D; "
    "SelfTabRedDotControl=%5B%7B%22id%22%3A%227640429815035594787%22%2C%22u%22%3A5%2C%22c%22%3A0%7D%2C%7B%22id%22%3A%227614971318500329524%22%2C%22u%22%3A15%2C%22c%22%3A0%7D%5D; "
    "sessionid=b1c6bbeeec646a183c18e5e55efdbf99; sessionid_ss=b1c6bbeeec646a183c18e5e55efdbf99; "
    "sid_guard=b1c6bbeeec646a183c18e5e55efdbf99%7C1781494226%7C5184000%7CFri%2C+14-Aug-2026+03%3A30%3A26+GMT; "
    "sid_tt=b1c6bbeeec646a183c18e5e55efdbf99; "
    "uid_tt=2d09ee5bc73d6b7cdee26a096673edf8; uid_tt_ss=2d09ee5bc73d6b7cdee26a096673edf8; "
    "sid_ucp_v1=1.0.0-KDUyYjRiNWEwZWI5NzA0ZWM1YjQ3ZDEyNjRmNTVjMDA0ZGQ2NDkzZDEKIQjrzJDK5c22BhDS473RBhjvMSAMMOqplq8GOAdA9AdIBBoCaGwiIGIxYzZiYmVlZWM2NDZhMTgzYzE4ZTVlNTVlZmRiZjk5; "
    "ssid_ucp_v1=1.0.0-KDUyYjRiNWEwZWI5NzA0ZWM1YjQ3ZDEyNjRmNTVjMDA0ZGQ2NDkzZDEKIQjrzJDK5c22BhDS473RBhjvMSAMMOqplq8GOAdA9AdIBBoCaGwiIGIxYzZiYmVlZWM2NDZhMTgzYzE4ZTVlNTVlZmRiZjk5; "
    "session_tlb_tag=sttt%7C20%7Csca77uxkahg8GOXlXv2_mf_________FaEWl-ypAe6RcOXxH5P7WEnmWM9aOMbiojuBpP5uMhbE%3D; "
    "strategyABtestKey=%221782095520.8%22; "
    "stream_recommend_feed_params=%22%7B%5C%22cookie_enabled%5C%22%3Atrue%2C%5C%22screen_width%5C%22%3A1920%2C%5C%22screen_height%5C%22%3A1080%2C%5C%22browser_online%5C%22%3Atrue%2C%5C%22cpu_core_num%5C%22%3A12%2C%5C%22device_memory%5C%22%3A32%2C%5C%22downlink%5C%22%3A1.45%2C%5C%22effective_type%5C%22%3A%5C%223g%5C%22%2C%5C%22round_trip_time%5C%22%3A350%7D%22; "
    "sdk_source_info=7e276470716a68645a606960273f276364697660272927676c715a6d6069756077273f2771777060272927666d776a68605a607d71606b766c6a6b5a7666776c7571273f275e58272927666a6b766a69605a696c6061273f27636469766027292762696a6764695a7364776c6467696076273f275e582729277672715a646971273f2763646976602729277f6b5a666475273f2763646976602729276d6a6e5a6b6a716c273f2763646976602729276c6b6f5a7f6367273f27636469766027292771273f273d313c313633313434373d3234272927676c715a75776a716a666a69273f2763646976602778; "
    "ttwid=1%7Ct1F6Nm7XYpeQp_CqeupDpouR1PKLc43qD7tz9HxCtks%7C1782112889%7C07014d3f91b1dd7e70e07860a9b159b963911b3a5566da574b206e062b5a02e9; "
    "UIFID=ee69abbd54cdddb154b01110285f038c0f724c22a9fa6fa6ff8c47d6ab1f845c3343682867d9db9738fb6bd7f89e269ede4b8e52b82b9b380d56223ec1bbe22456a13e54ddcf5e9e97954c8cdb2bcc5c232e5657830fafa806424df234ac170a523bbc28bf62e28902ef8c398b01fdf5f5fa494dd7ca90cc6beb1e30cf37cd272740019f3a13790fb3b4dfd3b260c8352eff83d6c95c4785e2720088cd525c8f; "
    "UIFID_TEMP=ee69abbd54cdddb154b01110285f038c0f724c22a9fa6fa6ff8c47d6ab1f845c96bfed176ad155dc5bfc47b9b4de11a01c676bb84389b56f57979b157c61021f09c693aed8f2980d528ac93fcd9592a6; "
    "volume_info=%7B%22isUserMute%22%3Afalse%2C%22isMute%22%3Afalse%2C%22volume%22%3A0.952%7D"
)

API_CONFIG = {
    "headers": {
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7,zh-TW;q=0.6',
        'cache-control': 'no-cache',
        'pragma': 'no-cache',
        'priority': 'u=1, i',
        'referer': 'https://www.douyin.com/', 
        'sec-ch-ua': '"Microsoft Edge";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': BROWSER_USER_AGENT,
        # 优先读取环境变量，如果没有则使用 hardcoded 的 NEW_COOKIE
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

    # 【新增函数】获取指定表格中所有“视频链接”
    def get_all_video_links(self, app_token: str, table_id: str) -> set:
        """
        从飞书表格中获取所有“视频链接”列的值，并返回一个集合以便快速去重。
        """
        all_links = set()
        token = self._get_tenant_access_token()
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
        headers = {"Authorization": f"Bearer {token}"}
        
        page_token = ""
        while True:
            params = {"page_size": 500, "field_names": '["视频链接"]'} # 只请求需要的列
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
                    # 飞书链接字段的标准格式是 [{"link": "URL"}]
                    if isinstance(video_link_field, list) and len(video_link_field) > 0:
                        link_obj = video_link_field[0]
                        if isinstance(link_obj, dict) and "link" in link_obj:
                            all_links.add(link_obj["link"])
                    # 也兼容可能是纯文本URL的情况
                    elif isinstance(video_link_field, str) and video_link_field.startswith("http"):
                        all_links.add(video_link_field)

                if data.get("has_more"):
                    page_token = data.get("page_token")
                else:
                    break
            except Exception as e:
                print(f"请求飞书记录时发生异常: {e}")
                break # 发生异常时中断，避免无限循环
        
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
    result = crawler.get_user_videos(homepage_url, max_videos=4)
    
    if "error" in result:
        log_message(log_list, f"❌ 扫描失败: {result['error']}")
        return
        
    videos = result.get("videos", [])
    author_name = result.get("user_info", {}).get("nickname", "未知作者")
    
    log_message(log_list, f"✅ 扫描结束！作者: {author_name}, 共找到 {len(videos)} 个视频。")
    if not videos: return

    # 【新增步骤】: 从飞书获取已存在的视频链接进行去重
    log_message(log_list, "➡️ 准备工作: 从飞书获取已存在的视频链接以进行去重...")
    try:
        existing_video_links = feishu_api.get_all_video_links(FEISHU_APP_TOKEN, table_id)
        log_message(log_list, f"✅ 已获取 {len(existing_video_links)} 个现有链接。")
    except Exception as e:
        log_message(log_list, f"⚠️ 警告: 无法从飞书获取现有链接，将继续处理所有视频。错误: {e}")
        existing_video_links = set() # 如果获取失败，则默认为空集合，不影响后续流程

    # 【修改步骤】: 筛选出新的、未被记录的视频
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
    
    # 【修改步骤】: 循环处理筛选后的视频列表
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
