import os
import time
import datetime
import subprocess

# 要重新部署的项目名称
SERVICE_NAME = "willowy-alida/seven"

def redeploy_service():
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"\n==========================================")
    print(f"⏰ 触发重部署任务 | 当前时间: {now}")
    print(f"==========================================")

    # 每次执行时动态获取环境变量，确保安全
    koyeb_token = os.getenv("KOYEB_TOKEN")
    
    if not koyeb_token:
        print("❌ [错误] 找不到 KOYEB_TOKEN 环境变量！")
        print("💡 请确保在 ClawCloud 的容器环境变量设置中添加了 KOYEB_TOKEN。")
        return

    print(f"▶ 正在向 Koyeb 发送 [{SERVICE_NAME}] 的重新部署指令...")
    
    # 组合 Koyeb CLI 命令
    # Koyeb CLI 会自动读取系统中的 KOYEB_TOKEN 环境变量
    cmd = f"koyeb service redeploy {SERVICE_NAME}"
    
    try:
        start_time = time.time()
        # 执行系统命令
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        cost_time = round(time.time() - start_time, 2)

        # 检查命令执行是否成功 (返回码 0 表示成功)
        if result.returncode == 0:
            print(f"✅ [成功] 重新部署指令已成功发送！")
            print(f"   └─ 目标项目: {SERVICE_NAME}")
            print(f"   └─ 耗时: {cost_time} 秒")
            print(f"   └─ Koyeb 返回信息: {result.stdout.strip() or '无详细信息'}")
        else:
            print(f"❌ [失败] 发送重新部署指令失败！")
            print(f"   └─ 错误码: {result.returncode}")
            print(f"   └─ 错误信息: {result.stderr.strip()}")
            
    except Exception as e:
         print(f"❌ [系统异常] 运行 Koyeb CLI 时发生错误: {str(e)}")

    print(f"==========================================")
    print(f"⏳ 任务结束，等待 5 分钟后进行下一次唤醒...")
    print(f"==========================================")

if __name__ == "__main__":
    print("🚀 Koyeb 自动重部署服务已启动容器...")
    print(f"🎯 目标应用: {SERVICE_NAME}")
    
    # 无限循环，每 50 分钟（3000秒）执行一次
    while True:
        redeploy_service()
        time.sleep(3000)
