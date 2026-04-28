# README
- 项目定位：Nonebot2 机器人（群管理 + AI 助手）
- 入口文件：`bot.py`（nonebot.init + load_from_toml）
- 本地启动：`python bot.py`
- 配置入口：`.env` / `.env.dev`
- LLM 配置：`src/settings/ai_assistant_config.py` 内配置 `api_key/base_url/model`
- 插件目录：`src/plugins`、`src/vendors`
- 数据目录：`data/`
- Bot 对接配置：`BOT_API_SECRETS` 或 `BOT_API_BOT_ID`/`BOT_API_SECRET`
- Bot 登录会话：`BOT_API_SESSION_TTL_SECONDS`/`BOT_API_COOKIE_SECURE`
