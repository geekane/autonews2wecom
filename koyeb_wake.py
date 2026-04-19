import os
import time
import datetime
import subprocess

# 要重新部署的项目名称
SERVICE_NAME = "willowy-alida/seven"

# 【新增】版本标识，每次修改代码可以改一下这里，比如改成 v1.2，用于确认 Docker 是否更新
VERSION = "v1.1 (调试排错专用版)"

def redeploy_service():
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"\n==========================================")
    print(f"⏰[版本: {VERSION}] 触发重部署任务 | 当前时间: {now}")
    print(f"==========================================")

    koyeb_token = os.getenv("KOYEB_TOKEN")
    
    if not koyeb_token:
        print("❌ [错误] 找不到 KOYEB_TOKEN 环境变量！")
        return

    print(f"▶ 正在向 Koyeb 发送 [{SERVICE_NAME}] 的重新部署指令...")
    
    cmd = f"koyeb service redeploy {SERVICE_NAME}"
    
    try:
        start_time = time.time()
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        cost_time = round(time.time() - start_time, 2)

        if result.returncode == 0:
            print(f"✅ [成功] 重新部署指令已成功发送！")
            print(f"   └─ 耗时: {cost_time} 秒")
            print(f"   └─ 返回: {result.stdout.strip() or '无详细信息'}")
        else:
            print(f"❌ [失败] 发送重新部署指令失败！")
            print(f"   └─ 错误码: {result.returncode}")
            print(f"   └─ 信息: {result.stderr.strip()}")
            
    except Exception as e:
         print(f"❌ [系统异常] 运行 Koyeb CLI 时发生错误: {str(e)}")

    print(f"==========================================")
    print(f"⏳ 任务执行完毕，准备执行 time.sleep(3000)")
    print(f"==========================================")


if __name__ == "__main__":
    # 【关键修改】这部分代码只有在容器/程序“刚启动”时才会执行一次
    startup_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print("\n" + "🌟"*20)
    print(f"🚀 [容器/脚本真正启动] ")
    print(f"📌 当前版本: {VERSION}")
    print(f"⏱️ 启动时间: {startup_time}")
    print(f"🎯 目标应用: {SERVICE_NAME}")
    print("🌟"*20 + "\n")
    
    loop_count = 1
    
    while True:
        print(f"\n---> 开始执行第 【{loop_count}】 次循环 <---")
        
        redeploy_service()
        
        print(f"💤 第 【{loop_count}】 次循环结束，开始休眠 1800 秒 (30分钟)...")
        print(f"🔍 排错指南: 请观察 5 分钟后，日志是打印了“第 {loop_count + 1} 次循环”，还是重新打印了“🌟 [容器/脚本真正启动]”")
        
        time.sleep(1800)
        
        loop_count += 1
