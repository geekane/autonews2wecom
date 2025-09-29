import asyncio
import json
import logging
import os
import requests
import sys  # 【新增】导入 sys 模块，用于控制脚本退出状态
import time

from playwright.async_api import async_playwright, TimeoutError

# --- 配置日志 ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s'
)

def send_wechat_notification(webhook_url, message):
    """发送企业微信机器人通知。"""
    if not webhook_url:
        logging.warning("未配置有效的企业微信 Webhook URL，跳过发送通知。")
        return

    payload = { "msgtype": "text", "text": { "content": message, "mentioned_list": ["@all"] } }
    headers = {"Content-Type": "application/json"}

    logging.info("正在发送企业微信通知...")
    try:
        response = requests.post(webhook_url, headers=headers, data=json.dumps(payload), timeout=15)
        response.raise_for_status()
        response_json = response.json()
        if response_json.get("errcode") == 0:
            logging.info("企业微信通知发送成功。")
        else:
            logging.error(f"企业微信通知发送失败: {response_json.get('errmsg', '未知错误')}")
    except requests.exceptions.RequestException as e:
        logging.error(f"发送企业微信通知时发生网络错误: {e}")
    except Exception as e:
        logging.error(f"发送企业微信通知时发生未知异常: {e}", exc_info=True)


async def main():
    """主函数：自动登录抖音来客，提取客服名单，对比后仅在名单变更时发送企业微信通知。"""
    # --- 1. 配置信息 ---
    cookie_file = '来客.json'
    target_url = "https://life.douyin.com/cs/web/distributary/group?accountId=1768205901316096&conGroupId=536920&groupId=1768205901316096&lifeAccountId=7241078611527075855"
    wechat_webhook_url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=0e364220-efc0-4e7b-b505-129ea3371053"
    KNOWN_AGENTS = ["杨蕊嘉行政", "宋华新", "吴东桧"]

    # --- 2. 检查 Cookie 文件 ---
    if not os.path.exists(cookie_file):
        logging.error(f"错误: Cookie 文件 '{cookie_file}' 未找到。")
        # 如果启动时关键文件就缺失，可以考虑发送通知并以失败状态退出
        send_wechat_notification(wechat_webhook_url, f"【抖音来客】脚本启动失败！\n\n错误信息: Cookie 文件 '{cookie_file}' 未找到。")
        sys.exit(1)

    # --- 3. 启动 Playwright ---
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = None  # 提前声明 page 变量

        # --- 4. 加载 Cookies ---
        try:
            with open(cookie_file, 'r', encoding='utf-8') as f:
                await context.add_cookies(json.load(f)['cookies'])
        except Exception as e:
            logging.error(f"加载 Cookie 文件失败: {e}")
            send_wechat_notification(wechat_webhook_url, f"【抖音来客】脚本启动失败！\n\n错误信息: 加载 Cookie 文件失败: {e}")
            await browser.close()
            sys.exit(1)

        # --- 5. 导航到页面并执行操作 ---
        try:
            page = await context.new_page()
            
            logging.info(f"开始初次导航至目标网址，并等待网络空闲...")
            await page.goto(target_url, wait_until="networkidle", timeout=60000)

            if target_url not in page.url:
                logging.warning(f"页面被重定向至: {page.url}。正在执行校正导航...")
                await page.goto(target_url, wait_until="networkidle", timeout=60000)

            logging.info("页面加载流程完成，当前URL正确。")

            group_locator = page.locator(".optionsItemTitle-dWtHOi").filter(has_text="默认接待组")

            logging.info("正在查找并点击'默认接待组' (自动等待最多15秒)...")
            await group_locator.click(timeout=15000)
            logging.info("✅ 已成功点击'默认接待组'。")
            
            await page.wait_for_timeout(2000)

            name_selector = "span.life-im-typography.life-im-typography-ellipsis.life-im-typography-text"
            scraped_names = sorted([name for name in await page.locator(name_selector).all_inner_texts() if "客服人数" not in name and name.strip() != ""])

            if scraped_names:
                logging.info(f"成功提取到 {len(scraped_names)} 位客服。")
                if set(scraped_names) != set(KNOWN_AGENTS):
                    logging.warning("检测到客服名单发生变更！准备发送通知。")
                    added = sorted(list(set(scraped_names) - set(KNOWN_AGENTS)))
                    removed = sorted(list(set(KNOWN_AGENTS) - set(scraped_names)))
                    
                    msg_parts = ["【抖音来客】客服名单变更提醒！\n"]
                    msg_parts.append(f"🔗 查看详情确认是否需要删除新增客服: https://life.douyin.com/cs/web/distributary/group?accountId=1768205901316096&conGroupId=536920&groupId=1768205901316096&lifeAccountId=7241078611527075855")
                    if added: msg_parts.append(f"🔴 新增客服:\n" + "\n".join(f"  + {name}" for name in added))
                    if removed: msg_parts.append(f"🔵 移除客服:\n" + "\n".join(f"  - {name}" for name in removed))
                    msg_parts.append(f"\n✨ 当前最新名单 ({len(scraped_names)}人):\n" + "\n".join(f"  • {name}" for name in scraped_names))
                    
                    send_wechat_notification(wechat_webhook_url, "\n".join(msg_parts))
                else:
                    logging.info("客服名单与基准名单一致，无需通知。")
            else:
                logging.warning("未能提取到任何客服姓名，请检查页面结构是否已更改。")
                screenshot_path = f"debug_screenshot_no_names_{int(time.time())}.png"
                await page.screenshot(path=screenshot_path, full_page=True)
                logging.info(f"已截取当前页面保存为 '{screenshot_path}'。")
                # 这种属于警告，但也算是一种失败场景，所以也以失败状态退出以触发截图上传
                send_wechat_notification(wechat_webhook_url, f"【抖音来客】脚本警告！\n\n未能提取到任何客服姓名，请检查页面结构。\n已保存截图: {screenshot_path}")
                sys.exit(1)

        except (TimeoutError, Exception) as e:
            error_type = "操作超时" if isinstance(e, TimeoutError) else "未知异常"
            logging.error(f"捕获到{error_type}: {e}", exc_info=True)
            
            if page and not page.is_closed():
                screenshot_path = f"error_screenshot_{int(time.time())}.png"
                try:
                    await page.screenshot(path=screenshot_path, full_page=True)
                    logging.info(f"已截取当前页面保存为 '{screenshot_path}' 以便调试。")
                except Exception as screenshot_e:
                    logging.error(f"尝试保存截图时发生错误: {screenshot_e}")
            else:
                logging.warning("Page 对象不存在或已关闭，无法进行截图。")
                
            sys.exit(1)

        finally:
            logging.info("操作流程结束，正在关闭浏览器...")
            # 【优化】增加检查，确保 browser 对象有效
            if 'browser' in locals() and browser.is_connected():
                await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
