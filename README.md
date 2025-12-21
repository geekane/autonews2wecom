# AutoNews2WeCom & Business Automation Tools

这是一个基于 Python 的自动化工具集，主要用于资讯抓取推送、飞书/抖音平台数据同步、以及基于视觉 AI 的聊天记录监控。

## 核心功能

### 1. 硬件游戏资讯推送 ([`news.py`](news.py))
- **功能**: 自动从 `rebang.today`（集成爱范儿、蓝点网、36Kr等）抓取技术热榜。
- **AI 过滤**: 调用 SiliconFlow (Qwen2.5) API，利用大模型能力自动筛选与“电脑硬件”和“电子游戏”相关的资讯。
- **推送**: 将筛选后的资讯（标题 + 链接）通过 Webhook 发送到企业微信机器人。

### 2. 抖音数据同步至飞书 ([`sync_douyin_to_feishu.py`](sync_douyin_to_feishu.py))
- **功能**: 接入抖音生活服务（本地生活）Open API。
- **逻辑**: 自动获取指定账号下所有门店（POI）的在线商品 ID，并与飞书多维表格（Bitable）中的既有数据进行比对。
- **同步**: 自动将新增的商品 ID 批量写入飞书多维表格，实现自动化库存或商品台账同步。

### 3. 飞书聊天记录监控 ([`飞书聊天.py`](飞书聊天.py))
- **功能**: 结合 Playwright 自动化与视觉大模型（Qwen-VL）。
- **逻辑**: 自动登录飞书网页版并截取指定群聊界面。
- **视觉分析**: 将截图发送至 ModelScope (Qwen-VL) 进行视觉识别，提取新消息内容及发言人。
- **持久化**: 将识别到的对话内容增量保存至 [`chat_log.csv`](chat_log.csv)。

### 4. 其他业务脚本
- **经营数据管理**: 包括经营分更新 ([`经营分.py`](经营分.py))、门店数据维护 ([`更新门店数据.py`](更新门店数据.py))。
- **退款与评价**: [`收集退款信息.py`](收集退款信息.py) 和 [`同步评价信息.py`](同步评价信息.py) 用于自动化处理售后与口碑数据。
- **简报生成**: [`生成每日简报.py`](生成每日简报.py) 用于汇总每日经营指标。

## 环境要求

- Python 3.8+
- 依赖项安装:
  ```bash
  pip install -r requirements.txt
  ```
- 浏览器驱动: 
  - 部分功能依赖 `playwright`，需运行 `playwright install chromium`。
  - [`news.py`](news.py) 可能需要 [`chromedriver`](chromedriver)。

## 环境变量配置

运行前请确保在 `.env` 或系统环境变量中配置以下密钥：

- `DOUYIN_APP_ID` / `DOUYIN_APP_SECRET`: 抖音开放平台凭据
- `FEISHU_APP_ID` / `FEISHU_APP_SECRET`: 飞书自建应用凭据
- `WECOM_WEBHOOK_KEY`: 企业微信群机器人 Webhook Key
- `SILICONFLOW_API_KEY`: SiliconFlow (Qwen) API 密钥
- `MODELSCOPE_API_KEY`: 魔搭社区 API 密钥（用于视觉模型）

## 项目结构说明

- `*.py`: 各类功能脚本。
- `*.json`: 存储 Session、Cookie 或本地配置。
- `*.xlsx` / `*.csv`: 业务数据表及日志。