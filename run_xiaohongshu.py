import asyncio
import json
import os
import requests
from playwright.async_api import async_playwright, Playwright

# --- 1. 配置信息 ---
IMAGE_URLS = [
    "https://ts4.tc.mm.bing.net/th/id/OIP-C.OGQGFSOUQj7hfTfo7SpNxwHaEZ?r=0&rs=1&pid=ImgDetMain&o=7&rm=3",
    "https://tse2-mm.cn.bing.net/th/id/OIP-C.MRugezZCy4HWjVrB0nlnfgHaD4?r=0&o=7rm=3&rs=1&pid=ImgDetMain&o=7&rm=3"
]
NOTE_TITLE = "由 GitHub Actions 自动发布的笔记！"
NOTE_DESCRIPTION = "这是通过 Playwright 在服务器上自动执行发布的笔记内容。\n#GitHubActions #自动化 #Python"
TEMP_IMAGE_DIR = "temp_images"
SCREENSHOT_FILE = "final_screenshot.png"

# --- 2. 辅助函数 (保持不变) ---
def clean_cookies(cookies: list) -> list:
    valid_same_site_values = {"Lax", "Strict", "None"}
    cleaned_cookies = []
    for cookie in cookies:
        if 'sameSite' in cookie and cookie['sameSite'] not in valid_same_site_values:
            cookie['sameSite'] = 'Lax'
        cleaned_cookies.append(cookie)
    return cleaned_cookies

def download_images(urls: list, download_dir: str) -> list:
    print(f"📁 准备下载图片到 ./{download_dir}/ 文件夹...")
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)
    local_paths = []
    headers = {'User-Agent': 'Mozilla/5.0'}
    for i, url in enumerate(urls):
        try:
            response = requests.get(url, headers=headers, timeout=15)
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

# --- 3. 主运行函数 (已修改) ---
async def run(playwright: Playwright):
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

    # 在服务器上必须使用 headless=True
    browser = await playwright.chromium.launch(headless=True, slow_mo=50)
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
        await page.screenshot(path="error_screenshot.png") # 失败时也截图
        await browser.close()
        return

    print("✍️ 正在填写笔记标题和描述...")
    await page.get_by_placeholder("填写标题，可能会有更多赞哦～").fill(NOTE_TITLE)
    await page.locator(".ProseMirror").fill(NOTE_DESCRIPTION)
    print("✅ 标题和描述填写完毕。")

    # 等待片刻，确保所有前端渲染完成
    await page.wait_for_timeout(3000)

    # --- 截取最终成果图 ---
    print(f"📸 正在截取最终页面... 保存为 {SCREENSHOT_FILE}")
    await page.screenshot(path=SCREENSHOT_FILE, full_page=True)
    print("✅ 截图成功！")

    # --- (可选) 自动点击发布按钮 ---
    # !!! 警告: 自动发布风险高，请确保所有内容无误再取消下面的注释 !!!
    # try:
    #     print("🚀 准备点击发布按钮...")
    #     publish_button = page.get_by_role("button", name="发布", exact=True)
    #     await publish_button.click()
    #     print("✅ 发布按钮已点击！等待发布成功...")
    #     # 这里可以加一个等待发布成功的确认逻辑，比如等待URL变化或出现“发布成功”的提示
    #     await page.wait_for_timeout(10000) # 等待10秒让发布完成
    #     await page.screenshot(path="published_screenshot.png")
    # except Exception as e:
    #     print(f"❌ 点击发布按钮失败: {e}")


    await browser.close()
    print("👋 浏览器已关闭。")

async def main():
    async with async_playwright() as playwright:
        await run(playwright)

if __name__ == "__main__":
    asyncio.run(main())
