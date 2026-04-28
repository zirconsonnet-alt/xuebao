---
project: xuebao
type: data-models
generated_at: "2026-02-06"
---

# 数据模型（SQLite）

## 1. 存储位置

- 群数据：`data/group_management/<group_id>/group_data.db`
- 账号对接：`data/internal_api.db`

## 2. 主要表（摘录）

核心表与不变量概览可参考：`docs/DOMAIN_MODEL.md`。

### 投票/会话/审计

- `sessions`：会话状态（version CAS、expires_at）
- `audit_events` / `audit_logs`：审计（以 `audit_events` 为主）
- `idempotency_keys`：幂等键表（idem_key PK）
- `vote_records`：投票记录（PK: session_key,user_id）

### 经济系统（points/honor）

- `points_ledger`：统一账本
  - UNIQUE: `idempotency_key`
  - balance = SUM(delta) by (group_id,user_id,currency)
- `sign_in_records`：每日签到幂等（PK: group_id,user_id,sign_date）
- `topic_create_requests`：议题创建扣费幂等（PK: group_id,request_key）
- `topic_votes`：议题投票参与幂等（PK: group_id,topic_id,user_id）

## 3. 迁移策略

- 变更优先增量：`CREATE TABLE IF NOT EXISTS` / `ALTER TABLE`
- 需要数据修复/重建表时：集中在 `GroupDatabase._migrate_schema()`（避免散落在业务逻辑中）

