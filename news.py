def send_to_wechat_bot(content):
    """
    发送消息到企业微信机器人
    """
    webhook_key = os.getenv('WECOM_WEBHOOK_KEY')  # 从环境变量中获取 key
    webhook_url = f'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={webhook_key}'
    data = {
        "msgtype": "text",
        "text": {
            "content": content
        }
    }
    try:
        response = requests.post(webhook_url, json=data)
        response.raise_for_status()  # 如果响应状态码不是200，抛出异常
        return response.status_code == 200
    except requests.exceptions.RequestException as e:
        print(f"发送消息到企业微信机器人失败: {e}")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--driver_path", help="Path to chromedriver")
    parser.add_argument("--chromium_path", help="Path to chrome")
    args = parser.parse_args()

    url = 'https://rebang.today/tech?tab=ithome'
    # 请根据实际情况修改driver路径，如果driver在系统路径中，可以不传
    html = fetch_hot_news(url, driver_path=args.driver_path, chromium_path = args.chromium_path)
    if html:
        news_list = parse_html(html)
        if news_list:
            # 格式化成文本，只保留标题
            content = "今日热点:\n"
            for item in news_list:
                content += f"- {item['title']}\n"
            # 发送企业微信
            success = send_to_wechat_bot(content)
            if success:
                print("消息发送成功")
            else:
                print("消息发送失败")
        else:
            print('没有找到热点信息')
    else:
        print('获取页面信息失败')
