# 文件名: 飞书聊天.py

import os
import time
import base64
import json
import pandas as pd
from datetime import datetime
import pytz
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from openai import OpenAI

# --- 全局配置 ---
MODEL_ID = 'Qwen/Qwen3-VL-30B-A3B-Instruct'
CSV_LOG_FILE = 'chat_log.csv'
SUCCESS_SCREENSHOT_FILE = 'feishu_screenshot.png'
ERROR_SCREENSHOT_FILE = 'error_screenshot.png' 
COOKIE_FILE = '飞书.json'
BEIJING_TZ = pytz.timezone('Asia/Shanghai')

# --- AI 视觉模型分析模块 ---
def analyze_new_messages(api_key, image_path, previous_messages_context):
    print("正在准备将截图发送给AI进行分析...")
    try:
        with open(image_path, "rb") as image_file:
            base64_image = base64.b64encode(image_file.read()).decode('utf-8')
        image_data_url = f"data:image/png;base64,{base64_image}"
    except Exception as e:
        print(f"读取或编码图片失败: {e}")
        return []
    
    client = OpenAI(base_url='https://api-inference.modelscope.cn/v1', api_key=api_key)
    
    # 【修改】优化Prompt，要求更严格的JSON输出
    prompt = f"""
    这是最近的5条聊天记录作为上下文：
    --- CONTEXT ---
    {previous_messages_context if previous_messages_context else "无历史记录。"}
    --- END CONTEXT ---

    现在，请仔细分析下面的截图。你的任务是：
    1. 识别出截图中所有**未出现在**上述上下文中的**新消息**。
    2. 将这些新消息以结构化的JSON格式返回。JSON必须是一个列表，每个元素包含 "speaker" 和 "content" 两个键。
    3. **非常重要**: 你的回答必须是纯粹的、不含任何解释、不含Markdown标记的原始JSON字符串。

    如果截图中没有新消息，请返回一个空列表 `[]`。
    """
    
    print(f"正在调用AI模型 ({MODEL_ID})...")
    try:
        response = client.chat.completions.create(
            model=MODEL_ID,
            messages=[{'role': 'user', 'content': [{'type': 'text', 'text': prompt}, {'type': 'image_url', 'image_url': {'url': image_data_url}}]}]
        )
        response_text = response.choices[0].message.content
        
        # 【关键修改】在解析前进行检查和清理
        print("AI 原始返回:", response_text)
        if not response_text or not response_text.strip():
            print("AI返回为空，判定为无新消息。")
            return []

        # 清理可能的Markdown标记
        if response_text.strip().startswith("```json"):
            response_text = response_text.strip()[7:-3].strip()
        elif response_text.strip().startswith("```"):
             response_text = response_text.strip()[3:-3].strip()

        # 再次检查清理后是否为空
        if not response_text:
            print("清理Markdown后内容为空，判定为无新消息。")
            return []

        new_messages = json.loads(response_text)
        return new_messages if isinstance(new_messages, list) else []
    
    except json.JSONDecodeError as e:
        print(f"AI返回的不是有效的JSON格式，解析失败: {e}")
        print(f"无法解析的内容: {response_text}")
        return []
    except Exception as e:
        print(f"调用AI模型时出错: {e}")
        return []

# --- Playwright 自动化模块 (无变化) ---
def capture_feishu_chat():
    if not os.path.exists(COOKIE_FILE):
        print(f"错误: 找不到 Cookie 文件 '{COOKIE_FILE}'。")
        return False, None
    screenshot_path = None
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=COOKIE_FILE)
        page = context.new_page()
        try:
            print("正在跳转到飞书...")
            page.goto("https://www.feishu.cn/messenger/", wait_until='domcontentloaded', timeout=60000)
            print("等待页面元素加载...")
            time.sleep(10)
            print("正在查找并点击 '直播内部讨论群'...")
            target_chat = page.get_by_text("直播内部讨论群", exact=True)
            target_chat.click(timeout=15000)
            print("点击成功！")
            print("点击后等待5秒，让右侧聊天内容渲染...")
            time.sleep(5)
            screenshot_path = SUCCESS_SCREENSHOT_FILE
            page.screenshot(path=screenshot_path, full_page=True)
            print(f"全页面截图成功，已保存至: {screenshot_path}")
            return True, screenshot_path
        except PlaywrightTimeoutError as e:
            print("\n" + "="*50)
            print("！！！Playwright操作超时失败，正在截取当前屏幕画面...！！！")
            print("="*50)
            error_screenshot_path = ERROR_SCREENSHOT_FILE
            page.screenshot(path=error_screenshot_path, full_page=True)
            print(f"已将错误画面保存至: {error_screenshot_path}")
            print(f"\n详细错误信息: {e}")
            return False, None
        except Exception as e:
            print(f"发生未知错误: {e}")
            return False, None
        finally:
            browser.close()
            print("浏览器已关闭。")

# --- 主程序 (无变化) ---
def main():
    try:
        df = pd.read_csv(CSV_LOG_FILE) if os.path.exists(CSV_LOG_FILE) else pd.DataFrame(columns=['timestamp', 'speaker', 'content'])
    except Exception as e:
        print(f"读取CSV文件失败: {e}")
        return
    context_str = "\n".join([f"{row['speaker']}: {row['content']}" for _, row in df.tail(5).iterrows()])
    success, screenshot_file = capture_feishu_chat()
    if not success:
        print("截图失败，任务终止。")
        return
    api_key = os.getenv('MODELSCOPE_API_KEY')
    if not api_key:
        print("错误: 缺少环境变量 MODELSCOPE_API_KEY。")
        return
    new_messages = analyze_new_messages(api_key, screenshot_file, context_str)
    if new_messages:
        print(f"AI识别到 {len(new_messages)} 条新消息，正在写入CSV...")
        current_time_beijing = datetime.now(BEIJING_TZ).strftime('%Y-%m-%d %H:%M:%S')
        new_records = [{'timestamp': current_time_beijing, 'speaker': msg.get('speaker'), 'content': msg.get('content')} for msg in new_messages if 'speaker' in msg and 'content' in msg]
        if new_records:
            updated_df = pd.concat([df, pd.DataFrame(new_records)], ignore_index=True)
            updated_df.to_csv(CSV_LOG_FILE, index=False)
            print("CSV文件更新成功！")
    else:
        print("未发现新消息。")

if __name__ == "__main__":
    main()
