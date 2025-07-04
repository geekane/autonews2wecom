import asyncio
import json
import os
import requests # 用于下载图片
import time
from playwright.async_api import async_playwright, Playwright

# --- 1. 配置信息 ---
# 要上传的图片URL列表
IMAGE_URLS = [
    "https://ts4.tc.mm.bing.net/th/id/OIP-C.OGQGFSOUQj7hfTfo7SpNxwHaEZ?r=0&rs=1&pid=ImgDetMain&o=7&rm=3",
    "https://tse2-mm.cn.bing.net/th/id/OIP-C.MRugezZCy4HWjVrB0nlnfgHaD4?r=0&o=7rm=3&rs=1&pid=ImgDetMain&o=7&rm=3"
]

# 笔记的标题和描述
NOTE_TITLE = "这是一个用Playwright自动发布的笔记标题！"
NOTE_DESCRIPTION = "这是笔记的描述内容。\n#自动化测试 #Python #Playwright"

# 临时存放下载图片的文件夹
TEMP_IMAGE_DIR = "temp_images"

# --- 2. 辅助函数 ---

def clean_cookies(cookies: list) -> list:
    """修正 cookie 列表以兼容 Playwright。"""
    valid_same_site_values = {"Lax", "Strict", "None"}
    cleaned_cookies = []
    for cookie in cookies:
        if 'sameSite' in cookie and cookie['sameSite'] not in valid_same_site_values:
            cookie['sameSite'] = 'Lax'
        cleaned_cookies.append(cookie)
    return cleaned_cookies

def download_images(urls: list, download_dir: str) -> list:
    """从URL下载图片到本地，并返回本地文件路径列表。"""
    print(f"📁 准备下载图片到 ./{download_dir}/ 文件夹...")
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)
        print(f"   - 创建文件夹: {download_dir}")

    local_paths = []
    headers = { # 模拟浏览器请求头，防止被服务器拒绝
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    for i, url in enumerate(urls):
        try:
            response = requests.get(url, headers=headers, stream=True, timeout=15)
            response.raise_for_status() # 如果请求失败则抛出异常
            
            # 从URL或Content-Type猜测文件扩展名
            content_type = response.headers.get('content-type', '')
            if 'jpeg' in content_type or 'jpg' in content_type:
                ext = '.jpg'
            elif 'png' in content_type:
                ext = '.png'
            else:
                ext = '.jpg' # 默认使用 .jpg
            
            file_path = os.path.join(download_dir, f"image_{i}{ext}")
            
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            local_paths.append(os.path.abspath(file_path))
            print(f"   ✅ 下载成功: {url} -> {file_path}")

        except requests.exceptions.RequestException as e:
            print(f"   ❌ 下载失败: {url} | 错误: {e}")

    return local_paths

# --- 3. 主运行函数 ---

async def run(playwright: Playwright):
    """
    主运行函数：加载Cookie，下载并上传图片，填写内容，然后暂停。
    """
    # 下载图片
    local_image_paths = download_images(IMAGE_URLS, TEMP_IMAGE_DIR)
    if not local_image_paths:
        print("❌ 没有成功下载任何图片，脚本终止。")
        return

    # 加载 Cookie
    try:
        with open('小红书.json', 'r', encoding='utf-8') as f:
            cookies = clean_cookies(json.load(f))
        print("✅ Cookie 文件 '小红书.json' 加载并清理成功。")
    except Exception as e:
        print(f"❌ 加载Cookie失败: {e}")
        return

    # 启动浏览器
    browser = await playwright.chromium.launch(headless=False, slow_mo=100)
    context = await browser.new_context()
    await context.add_cookies(cookies)
    page = await context.new_page()

    # 访问小红书发布页面
    target_url = "https://creator.xiaohongshu.com/publish/publish?from=menu&target=image"
    print(f"🚀 正在导航到: {target_url}")
    await page.goto(target_url, timeout=60000)
    await page.wait_for_load_state('networkidle')
    print("✨ 发布页面加载完成。")

    # --- 核心操作：上传图片 ---
    # 通常文件上传的 input 元素是隐藏的，我们直接定位它并设置文件
    print("🔍 正在定位文件上传元素...")
    # 这个定位器 'input[type="file"]' 非常通用，通常能找到隐藏的上传输入框
    file_input_locator = page.locator('input[type="file"]')
    
    try:
        print(f"⬆️ 正在上传 {len(local_image_paths)} 张图片...")
        await file_input_locator.set_input_files(local_image_paths, timeout=60000)
        print("✅ 图片文件已提交给页面。等待页面处理...")
        
        # 等待图片上传完成的标志，比如等待预览图出现
        # 这里我们等待第一个预览图出现作为上传成功的信号
        await page.locator('.upload-cover-image-container').first.wait_for(timeout=60000)
        print("🖼️ 图片预览已出现，上传成功！")

    except Exception as e:
        print(f"❌ 上传图片失败: {e}")
        print("   提示: 如果超时，可能是网络问题或页面结构已改变。请使用 Inspector 检查 'input[type=\"file\"]' 定位器是否正确。")
        await page.pause() # 出错时暂停，方便调试
        return

    # --- 填写笔记内容 ---
    print("✍️ 正在填写笔记标题和描述...")
    
    # 填写标题
    await page.get_by_placeholder("填写标题，可能会有更多赞哦～").fill(NOTE_TITLE)
    
    # 填写描述
    await page.locator(".ProseMirror").fill(NOTE_DESCRIPTION)
    
    print("✅ 标题和描述填写完毕。")
    
    # --- 设置断点，等待手动操作 ---
    print("\n" + "="*50)
    print("⏸️  脚本已暂停。所有内容已自动填充完毕！")
    print("👉  请在浏览器窗口中检查内容，添加话题、地点等信息。")
    print("👉  确认无误后，请手动点击【发布】按钮。")
    print("👉  您也可以在 Playwright Inspector 中继续调试。")
    print("="*50 + "\n")
    
    await page.pause() # 关键断点！

    print("\n▶️  脚本已从 Inspector 恢复执行。")
    
    # 清理下载的临时文件
    for path in local_image_paths:
        if os.path.exists(path):
            os.remove(path)
    if os.path.exists(TEMP_IMAGE_DIR):
        try:
            os.rmdir(TEMP_IMAGE_DIR)
            print(f"🧹 临时文件夹 '{TEMP_IMAGE_DIR}' 已清理。")
        except OSError:
            print(f"ℹ️ 临时文件夹 '{TEMP_IMAGE_DIR}' 非空，未被删除。")

    await context.close()
    await browser.close()
    print("👋 浏览器已关闭。")

async def main():
    async with async_playwright() as playwright:
        await run(playwright)

if __name__ == "__main__":
    asyncio.run(main())
