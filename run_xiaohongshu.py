# 文件路径: /run_xiaohongshu.py

import asyncio
import json
import os
import requests
from playwright.async_api import async_playwright, Playwright

# --- 1. 从环境变量读取所有配置 ---

# 从环境变量读取图片链接的 JSON 字符串，如果不存在则使用一个空列表的JSON
image_urls_json = os.getenv('IMAGE_URLS_JSON', '[]')
try:
    IMAGE_URLS = json.loads(image_urls_json)
    print(f"✅ 从环境变量成功加载 {len(IMAGE_URLS)} 个图片链接。")
except json.JSONDecodeError:
    print(f"❌ 解析环境变量 IMAGE_URLS_JSON 失败，将使用空列表。内容: {image_urls_json}")
    IMAGE_URLS = []

# 从环境变量读取标题和描述
NOTE_TITLE = os.getenv('NOTE_TITLE_FROM_API', "默认标题：由 GitHub Actions 自动发布")
NOTE_DESCRIPTION = os.getenv('NOTE_DESC_FROM_API', "默认描述：这是通过 Coze 插件 -> GitHub Actions 发布的笔记内容。\n#自动化 #Coze")

# 其他固定配置
TEMP_IMAGE_DIR = "temp_images"
SCREENSHOT_FILE = "final_screenshot.png"

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
    print(f"📁 准备下载 {len(urls)} 张图片到 ./{download_dir}/ 文件夹...")
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)
    local_paths = []
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
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
            print(f"   ✅ 下载成功: {url} -> {file_path}")
        except requests.exceptions.RequestException as e:
            print(f"   ❌ 下载失败: {url} | 错误: {e}")
    return local_paths

# --- 3. 主运行函数 ---

async def run(playwright: Playwright):
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
        print("✅ Cookie 文件加载并清理成功。")
    except Exception as e:
        print(f"❌ 加载Cookie失败: {e}")
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

async def main():
    async with async_playwright() as playwright:
        await run(playwright)

if __name__ == "__main__":
    asyncio.run(main())
