# CONTROL_MAP
## 入口→用例映射
- on_command(service_action)：由 service_manager 动态注册服务命令
- 命令/词云：由 application `WordcloudService` 承接（开关/生成/形状/定时），避免 vendors 插件 import 即注册响应器
- 命令/B话榜：由 application `DialectlistService` 承接（B话榜/看看B话），避免 vendors 插件 import 即注册响应器
- on_message/Emoji合成：由 application `EmojimixService` 承接（匹配 `emoji+emoji`），避免 vendors 插件 import 即注册响应器
- 命令/群服务：展示服务帮助与面板（run_flow）
- 命令/群活动：输出活动与管理命令提示
- 命令/撤回：删除被回复消息
- on_notice(群文件上传)：作品发布服务发送音乐卡片，并在 10 分钟内 waiter 监听“回复+表情(63)”触发设精
- on_message(私聊)：AI 助手回复
- AI tool 调用：service_bridge 扫描 @ai_tool 注册到 tool_registry
- AI tool 内置工具已移除，统一由服务层 @ai_tool 提供
- AI tool 门禁：用户输入/LLM 输出命中（正则或关键词）触发，追加系统提示并强制工具调用（tool_choice）
- 命令/test：AI 服务打印当前消息记录到后台日志
- on_notice(私聊戳一戳)：AI 菜单
- 定时任务：organize_files_fallback、release
- on_request：服务层自定义请求处理（动态注册）
- HTTP /internal/*：Bot 对接鉴权与账号同步（签名+nonce）
- HTTP /auth/login：网页端登录换取 session Cookie

## 副作用清单
- DB 写入 sessions：`src/services/metadata_commands.py` create/update/finish/cancel；幂等=session_key；审计=无；权限=服务内控；失败=返回 False
- DB 写入 audit_events/audit_logs：`src/services/metadata_commands.py` record_audit_event/log；幂等=无；审计=主记录；失败=尽力而为
- 审计真相源：audit_events 为主审计表；audit_logs 仅作兼容输出
- DB 写入 idempotency_keys：`src/services/metadata_commands.py` reserve_idempotency_key；幂等=idem_key；审计=可选；失败=阻断副作用
- DB 写入 vote_records：`src/services/metadata_commands.py` reserve_vote_record；幂等=PK(session_key,user_id)；审计=可选；失败=拒绝重复投票
- DB 写入 topics/members：`src/services/metadata_commands.py` add_topic/update_member_stats；幂等=无；审计=无；失败=异常抛出
- DB 写入 activities/participants/activity_applications：发起活动(申请)/通过活动(创建 activity,status=active)/报名活动(participants)；幂等=participants PK；审计=无；失败=返回 False/提示
- 群管理动作：禁言/踢人/设精/撤回/发消息；幂等=idem_key(投票副作用)；审计=audit_events；失败=按 Nonebot 异常处理
- 外部 HTTP：127.0.0.1 TTS/角色接口；幂等=无；审计=无；失败=打印错误
- 文件写入（词云形状）：`nonebot_plugin_wordcloud` localstore 下 `mask*.png`；幂等=覆盖写；审计=无；权限=管理员/超管；失败=提示并退出
- 文件写入（定时任务配置）：`data/scheduled_tasks.json`（reminder 统一管理）；幂等=task_id 覆盖；审计=无；权限=管理员；失败=提示并退出
- 外部 HTTP（头像下载）：userinfo/httpx 获取头像；幂等=无；审计=无；失败=降级默认头像或提示
- 文件写入（B话榜缓存）：`nonebot_plugin_dialectlist` localstore cache 下 `*.jpg`；幂等=覆盖写；审计=无；权限=默认；失败=降级默认头像
- 渲染（B话榜可视化）：htmlrender/playwright 将模板渲染为图片；幂等=无；审计=无；失败=仅发送文本榜单
- 外部 HTTP（Emoji合成）：请求 gstatic emojikitchen PNG；幂等=无；审计=无；失败=返回错误提示
- DB 写入 bot_users/bot_ranks：internal.provision/confirm；幂等=qq_uin UNIQUE；审计=无；失败=返回 4xx
- DB 写入 bot_nonce_uses：internal 签名校验；幂等=bot_id+nonce；审计=无；失败=拒绝请求
- DB 写入 bot_sessions：auth.login；幂等=无；审计=无；失败=401

## Flow 状态机
- vote_create：step=0(创建)->1(已设主题)->2(已设时长)->finished/cancelled/expired；TTL=600/投票时长+300；并发语义=version CAS
- run_flow：输入路由->子 flow 或 handler；超时/输入退出 终止；并发语义=单次交互

## 幂等覆盖矩阵
- 已覆盖：vote_start（idempotency_keys）、投票记录（vote_records）、投票副作用（idempotency_keys）
- 已覆盖：internal.provision（qq_uin UNIQUE）、internal nonce（bot_nonce_uses）
- 未覆盖：活动创建/报名、文件整理、撤回消息、定时广播、auth.login 会话
- 风险：未覆盖动作需补 idem_key 或 DB gate
- idem_key 规则：group_id + action + subject_type + subject_id + session_key + event_id/message_id + actor_user_id

## 故障排查路径
- 投票重复触发：查 idempotency_keys + sessions.status/version
- 投票结果未写：查 vote_records + audit_events
- 群管理动作未执行：查 audit_events + Nonebot 日志
- 定时任务未执行：查 apscheduler 日志与任务注册
