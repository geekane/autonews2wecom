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
# 您指定的模型ID
MODEL_ID = 'Qwen/Qwen3-VL-30B-A3B-Instruct'
# CSV文件名，用于存储聊天记录
CSV_LOG_FILE = 'chat_log.csv'
# 截图文件名
SCREENSHOT_FILE = 'feishu_screenshot.png'
# Cookie文件名，脚本会直接读取此文件
COOKIE_FILE = '飞书.json'
# 北京时区
BEIJING_TZ = pytz.timezone('Asia/Shanghai')

# --- AI 视觉模型分析模块 ---
def analyze_new_messages(api_key, image_path, previous_messages_context):
    """
    使用ModelScope的Qwen-VL模型分析截图，并结合上下文找出新消息。
    """
    print("正在准备将截图发送给AI进行分析...")
    try:
        with open(image_path, "rb") as image_file:
            base64_image = base64.b64encode(image_file.read()).decode('utf-8')
        image_data_url = f"data:image/png;base64,{base64_image}"
    except Exception as e:
        print(f"读取或编码图片失败: {e}")
        return []

    client = OpenAI(
        base_url='https://api-inference.modelscope.cn/v1',
        api_key=api_key,
    )

    # 构造带有上下文的、要求JSON输出的Prompt
    prompt = f"""
    这是最近的5条聊天记录作为上下文：
    --- CONTEXT ---
    {previous_messages_context if previous_messages_context else "无历史记录。"}
    --- END CONTEXT ---

    现在，请仔细分析下面的截图。你的任务是：
    1. 识别出截图中所有**未出现在**上述上下文中的**新消息**。
    2. 将这些新消息以结构化的JSON格式返回。
    3. JSON格式必须是一个列表，每个元素包含 "speaker" 和 "content" 两个键。
    
    例如：
    [
      {{"speaker": "李子超", "content": "这是第一条新消息。"}},
      {{"speaker": "张三", "content": "这是第二条新消息。"}}
    ]

    如果截图中没有新消息，请返回一个空列表 `[]`。
    """

    print(f"正在调用AI模型 ({MODEL_ID})...")
    try:
        response = client.chat.completions.create(
            model=MODEL_ID,
            messages=[{
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': prompt},
                    {'type': 'image_url', 'image_url': {'url': image_data_url}},
                ],
            }],
        )
        
        response_text = response.choices[0].message.content
        print("AI 原始返回:", response_text)
        
        # 解析AI返回的JSON字符串
        new_messages = json.loads(response_text)
        if isinstance(new_messages, list):
            return new_messages
        else:
            print("AI返回的不是一个列表，解析失败。")
            return []

    except json.JSONDecodeError:
        print("AI返回的不是有效的JSON格式，无法解析。")
        return []
    except Exception as e:
        print(f"调用AI模型时出错: {e}")
        return []

# --- Playwright 自动化模块 ---
def capture_feishu_chat():
    """
    登录飞书，点击群聊，并截取整个页面。
    """
    # 直接检查并使用本地的 '飞书.json' 文件
    if not os.path.exists(COOKIE_FILE):
        print(f"错误: 找不到 Cookie 文件 '{COOKIE_FILE}'。请确保该文件已添加到仓库中。")
        return False

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True) # 在Action中必须用 headless
        # 直接从文件路径加载 storage_state
        context = browser.new_context(storage_state=COOKIE_FILE)
        page = context.new_page()

        print("正在跳转到飞书...")
        try:
            page.goto("https://www.feishu.cn/messenger/", wait_until='domcontentloaded', timeout=60000)
        except PlaywrightTimeoutError:
            print("页面加载超时，脚本继续执行...")

        print("等待页面元素加载...")
        time.sleep(10) # 在无头模式下，等待时间可能需要更长

        try:
            print("正在查找并点击 '直播内部讨论群'...")
            target_chat = page.get_by_text("直播内部讨论群", exact=True)
            target_chat.click(timeout=15000)
            print("点击成功！")

            print("点击后等待5秒，让右侧聊天内容渲染...")
            time.sleep(5) 

            page.screenshot(path=SCREENSHOT_FILE, full_page=True)
            print(f"全页面截图成功，已保存至: {SCREENSHOT_FILE}")
            
        except Exception as e:
            print(f"Playwright操作失败: {e}")
            page.screenshot(path="error_screenshot.png") # 失败时也截图，方便调试
            return False
        finally:
            browser.close()
            print("浏览器已关闭。")
    return True

# --- 主程序 ---
def main():
    """
    主执行函数
    """
    # 1. 读取历史聊天记录
    try:
        if os.path.exists(CSV_LOG_FILE):
            df = pd.read_csv(CSV_LOG_FILE)
            print(f"成功读取 {len(df)} 条历史聊天记录。")
        else:
            df = pd.DataFrame(columns=['timestamp', 'speaker', 'content'])
            print("未找到历史记录文件，将创建新的。")
    except Exception as e:
        print(f"读取CSV文件失败: {e}")
        return

    # 2. 准备上下文
    last_5_messages = df.tail(5)
    context_str = "\n".join([f"{row['speaker']}: {row['content']}" for index, row in last_5_messages.iterrows()])

    # 3. 执行Playwright截图
    if not capture_feishu_chat():
        print("截图失败，任务终止。")
        return

    # 4. 调用AI分析新消息
    api_key = os.getenv('MODELSCOPE_API_KEY')
    if not api_key:
        print("错误: 缺少环境变量 MODELSCOPE_API_KEY。")
        return
        
    new_messages = analyze_new_messages(api_key, SCREENSHOT_FILE, context_str)

    # 5. 处理并保存新消息
    if new_messages:
        print(f"AI识别到 {len(new_messages)} 条新消息，正在写入CSV...")
        current_time_beijing = datetime.now(BEIJING_TZ).strftime('%Y-%m-%d %H:%M:%S')
        
        new_records = []
        for msg in new_messages:
            # 确保消息包含 speaker 和 content
            if 'speaker' in msg and 'content' in msg:
                new_records.append({
                    'timestamp': current_time_beijing,
                    'speaker': msg['speaker'],
                    'content': msg['content']
                })
        
        if new_records:
            new_df = pd.DataFrame(new_records)
            updated_df = pd.concat([df, new_df], ignore_index=True)
            updated_df.to_csv(CSV_LOG_FILE, index=False)
            print("CSV文件更新成功！")
        else:
            print("AI返回的数据格式不正确，无消息写入。")
    else:
        print("未发现新消息。")

if __name__ == "__main__":
    main()
