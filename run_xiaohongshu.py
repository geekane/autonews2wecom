# 文件路径: /run_xiaohongshu.py

import asyncio
import json
import os
import requests
from playwright.async_api import async_playwright, Playwright

# --- 1. 从环境变量读取动态配置 ---
image_urls_json = os.getenv('IMAGE_URLS_JSON', '[]')
try:
    IMAGE_URLS = json.loads(image_urls_json)
    print(f"✅ 从环境变量成功加载 {len(IMAGE_URLS)} 个图片链接。")
except json.JSONDecodeError:
    print(f"❌ 解析环境变量 IMAGE_URLS_JSON 失败，使用空列表。内容: {image_urls_json}")
    IMAGE_URLS = []

NOTE_TITLE = os.getenv('NOTE_TITLE_FROM_API', "默认标题")
NOTE_DESCRIPTION = os.getenv('NOTE_DESC_FROM_API', "默认描述")

# --- 2. 辅助函数 (不变) ---
def clean_cookies(cookies: list) -> list:
    valid_same_site_values = {"Lax", "Strict", "None"}
    cleaned_cookies = []
    for cookie in cookies:
        if 'sameSite' in cookie and cookie['sameSite'] not in valid_same_site_values:
            cookie['sameSite'] = 'Lax'
        cleaned_cookies.append(cookie)
    return cleaned_cookies

def download_images(urls: list, download_dir: str) -> list:
    print(f"📁 准备下载图片...")
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)
    local_paths = []
    headers = {'User-Agent': 'Mozilla/5.0'}
    for i, url in enumerate(urls):
        try:
            response = requests.get(url, headers=headers, timeout=20)
            response.raise_for_status()
            content_type = response.headers.get('content-type', '')
            ext = '.jpg' if 'jpeg' in content_type else '.png' if 'png' in content_type else '.jpg'
            file_path = os.path.join(download_dir, f"image_{i}{ext}")
            with open(file_path, 'wb') as f:
                f.write(response.content)
            local_paths.append(os.path.abspath(file_path))
            print(f"   ✅ 下载成功: {url}")
        except requests.exceptions.RequestException as e:
            print(f"   ❌ 下载失败: {url} | 错误: {e}")
    return local_paths

# --- 3. 主运行函数 ---
async def run(playwright: Playwright):
    if not IMAGE_URLS:
        print("❌ 图片链接列表为空，脚本终止。")
        return

    local_image_paths = download_images(IMAGE_URLS, "temp_images")
    if not local_image_paths:
        print("❌ 没有成功下载任何图片，脚本终止。")
        return

    # --- 核心修正：直接从文件加载 Cookie，这部分是正确的，保持不变 ---
    try:
        with open('小红书.json', 'r', encoding='utf-8') as f:
            cookies = clean_cookies(json.load(f))
        print("✅ Cookie 文件 '小红书.json' 加载并清理成功。")
    except Exception as e:
        print(f"❌ 加载Cookie文件失败: {e}")
        return

    browser = await playwright.chromium.launch(headless=True)
    context = await browser.new_context()
    await context.add_cookies(cookies) # 使用从文件加载的 cookie
    page = await context.new_page()

    # ... 后续的 Playwright 操作保持不变 ...
    target_url = "https://creator.xiaohongshu.com/publish/publish?from=menu&target=image"
    print(f"🚀 正在导航到: {target_url}")
    await page.goto(target_url, timeout=60000, wait_until="networkidle")
    print("✨ 发布页面加载完成。")

    try:
        file_input_locator = page.locator('input[type="file"]')
        await file_input_locator.set_input_files(local_image_paths, timeout=60000)
        await page.locator('.upload-cover-image-container').first.wait_for(timeout=60000)
        print("🖼️ 图片上传成功！")
    except Exception as e:
        print(f"❌ 上传图片失败: {e}")
        await page.screenshot(path="error_screenshot.png")
        await browser.close()
        return

    await page.get_by_placeholder("填写标题，可能会有更多赞哦～").fill(NOTE_TITLE)
    await page.locator(".ProseMirror").fill(NOTE_DESCRIPTION)
    print("✅ 标题和描述填写完毕。")
    
    await page.wait_for_timeout(3000)
    await page.screenshot(path="final_screenshot.png", full_page=True)
    print("✅ 截图成功！")

    await browser.close()
    print("👋 浏览器已关闭。")

async def main():
    async with async_playwright() as playwright:
        await run(playwright)

if __name__ == "__main__":
    asyncio.run(main())
