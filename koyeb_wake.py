import requests
import os
import datetime

# ================= 配置区域 =================
# 你可以在这里直接写死你的 Koyeb 应用地址，或者在 GitHub Secrets 设置 TARGET_URLS
# 多个地址用逗号分隔
TARGET_URLS = os.getenv("TARGET_URLS", "https://你的应用名字.koyeb.app")
# ===========================================

def wake_up():
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"==========================================")
    print(f"⏰ 开始执行唤醒任务 | 时间: {now}")
    print(f"==========================================")

    url_list = [url.strip() for url in TARGET_URLS.split(",") if url.strip()]
    
    if not url_list:
        print("❌ 错误: 未配置目标 URL，请检查环境变量 TARGET_URLS")
        return

    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36',
        'Cache-Control': 'no-cache'
    })

    for i, url in enumerate(url_list, 1):
        print(f"\n[任务 {i}] 正在尝试唤醒: {url}")
        try:
            # 发送 GET 请求
            response = session.get(url, timeout=15)
            
            # 详细日志输出
            if response.status_code == 200:
                print(f"✅ [成功] 目标响应正常！")
                print(f"   - 状态码: {response.status_code}")
                print(f"   - 响应大小: {len(response.text)} 字节")
            elif response.status_code == 503:
                print(f"⚠️ [提示] 服务可能正在启动中 (503)...")
            else:
                print(f"❓ [警告] 收到异常状态码: {response.status_code}")
                
        except requests.exceptions.Timeout:
            print(f"❌ [错误] 连接超时，目标可能已经彻底休眠或网络不通。")
        except requests.exceptions.ConnectionError:
            print(f"❌ [错误] 无法建立连接，请检查 URL 是否正确。")
        except Exception as e:
            print(f"❌ [未知错误] 发生异常: {str(e)}")

    print(f"\n==========================================")
    print(f"🏁 所有唤醒任务已完成 | 结束时间: {datetime.datetime.now().strftime('%H:%M:%S')}")
    print(f"==========================================")

if __name__ == "__main__":
    wake_up()
