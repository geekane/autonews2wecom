# 文件路径: /run_xiaohongshu.py

import asyncio
import json
import os
import requests
from playwright.async_api import async_playwright, Playwright

# --- 1. 从环境变量读取所有配置 (这部分保持不变) ---
image_urls_json = os.getenv('IMAGE_URLS_JSON', '[]')
try:
    IMAGE_URLS = json.loads(image_urls_json)
    print(f"✅ 从环境变量成功加载 {len(IMAGE_URLS)} 个图片链接。")
    print(f"   - 链接列表: {IMAGE_URLS}")
except json.JSONDecodeError:
    print(f"❌ 解析环境变量 IMAGE_URLS_JSON 失败，使用空列表。内容: {image_urls_json}")
    IMAGE_URLS = []

NOTE_TITLE = os.getenv('NOTE_TITLE_FROM_API', "默认标题")
NOTE_DESCRIPTION = os.getenv('NOTE_DESC_FROM_API', "默认描述")

TEMP_IMAGE_DIR = "temp_images"
SCREENSHOT_FILE = "final_screenshot.png"

# --- 2. 辅助函数 (重点优化) ---

def clean_cookies(cookies: list) -> list:
    # 这个函数不需要修改
    valid_same_site_values = {"Lax", "Strict", "None"}
    cleaned_cookies = []
    for cookie in cookies:
        if 'sameSite' in cookie and cookie['sameSite'] not in valid_same_site_values:
            cookie['sameSite'] = 'Lax'
        cleaned_cookies.append(cookie)
    return cleaned_cookies

def download_images(urls: list, download_dir: str) -> list:
    """
    (已优化) 从URL下载图片到本地，并返回本地文件路径列表。
    专为处理直接下载链接（如带签名的OSS链接）优化。
    """
    print(f"📁 准备下载 {len(urls)} 张图片...")
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)
        
    local_paths = []
    # 模拟一个更真实的浏览器请求头，增加迷惑性
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
        'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
        'Referer': 'https://www.google.com/' # 伪造一个来源
    }
    
    for i, url in enumerate(urls):
        try:
            print(f"   - 正在尝试下载第 {i+1} 张图片，URL: {url}")
            # 使用流式下载和超时设置
            with requests.get(url, headers=headers, stream=True, timeout=30) as r:
                r.raise_for_status() # 检查HTTP状态码是否为2xx
                
                # 从响应头中获取文件类型
                content_type = r.headers.get('content-type', '').lower()
                if 'jpeg' in content_type or 'jpg' in content_type:
                    ext = '.jpg'
                elif 'png' in content_type:
                    ext = '.png'
                elif 'webp' in content_type:
                    ext = '.webp'
                else:
                    ext = '.jpg' # 默认扩展名
                
                file_path = os.path.join(download_dir, f"image_{i}{ext}")
                
                # 以二进制块的方式写入文件，适合大文件
                with open(file_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192): 
                        f.write(chunk)
                        
                local_paths.append(os.path.abspath(file_path))
                print(f"   ✅ 下载成功 -> {file_path}")
                
        except requests.exceptions.RequestException as e:
            print(f"   ❌ 下载失败: {url} | 错误: {e}")
            # 即使部分失败，也继续尝试下载下一张
            continue
            
    return local_paths

# --- 3. 主运行函数 (保持不变) ---
async def run(playwright: Playwright):
    # ... (这部分的所有代码都不需要修改，与上一版完全相同) ...
    if not IMAGE_URLS:
        print("❌ 图片链接列表为空，脚本终止。")
        return

    local_image_paths = download_images(IMAGE_URLS, TEMP_IMAGE_DIR)
    if not local_image_paths:
        print("❌ 没有成功下载任何图片，脚本终止。")
        return

    try:
        with open('小红书.json', 'r', encoding='utf-8') as f:
            cookies = clean_cookies(json.load(f))
        print("✅ Cookie 文件 '小红书.json' 从仓库加载并清理成功。")
    except Exception as e:
        print(f"❌ 从仓库加载 '小红书.json' 文件失败: {e}")
        return

    browser = await playwright.chromium.launch(headless=True)
    context = await browser.new_context()
    await context.add_cookies(cookies)
    page = await context.new_page()

    target_url = "https://creator.xiaohongshu.com/publish/publish?from=menu&target=image"
    print(f"🚀 正在导航到: {target_url}")
    await page.goto(target_url, timeout=60000, wait_until="networkidle")
    print("✨ 发布页面加载完成。")

    try:
        print("🔍 正在定位文件上传元素...")
        file_input_locator = page.locator('input[type="file"]')
        await file_input_locator.set_input_files(local_image_paths, timeout=60000)
        await page.locator('.upload-cover-image-container').first.wait_for(timeout=60000)
        print("🖼️ 图片上传成功！")
    except Exception as e:
        print(f"❌ 上传图片失败: {e}")
        await page.screenshot(path="error_screenshot.png")
        await browser.close()
        return

    print("✍️ 正在填写笔记标题和描述...")
    await page.get_by_placeholder("填写标题，可能会有更多赞哦～").fill(NOTE_TITLE)
    await page.locator(".ProseMirror").fill(NOTE_DESCRIPTION)
    print("✅ 标题和描述填写完毕。")

    await page.wait_for_timeout(3000)

    print(f"📸 正在截取最终页面... 保存为 {SCREENSHOT_FILE}")
    await page.screenshot(path=SCREENSHOT_FILE, full_page=True)
    print("✅ 截图成功！")

    await browser.close()
    print("👋 浏览器已关闭。")

# --- 4. 入口 (保持不变) ---
async def main():
    async with async_playwright() as playwright:
        await run(playwright)

if __name__ == "__main__":
    asyncio.run(main())
