# TASK-005 核心数据库迁移与仓储骨架

| 字段 | 内容 |
| --- | --- |
| Task ID | `TASK-005` |
| 阶段 | Gate 1 |
| 状态来源 | `docs/tasks/TODO.md` |
| 依赖 | `TASK-004` |
| 参考文档 | `docs/agent-identity-permission-database-design.md` |
| 建议写入范围 | `migrations/**`、数据库模型文件、`packages/infrastructure/**` 中的 DB 与 repository 骨架 |
| 禁止改动范围 | 四份冻结基线文档、前端页面、审批/连接器业务逻辑 |

## 任务目标

实现第一批核心表的 SQLAlchemy 模型、Alembic 迁移和仓储骨架。

## 范围

- `users`
- `agent_identities`
- `delegation_credentials`
- `permission_requests`
- `permission_request_events`
- `approval_records`
- `access_grants`
- `audit_records`

## 交付物

- SQLAlchemy 模型
- 首批 Alembic 迁移
- 基础仓储接口与实现骨架

## 完成定义

- 数据库可迁移到首批结构
- 主外键、索引、约束与文档一致
- 仓储骨架可被后续服务直接复用

## 协作要求

- 任何表字段偏差都必须在备注中记录
