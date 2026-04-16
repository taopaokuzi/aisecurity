# TASK-015 审计查询与异常补偿 API

| 字段 | 内容 |
| --- | --- |
| Task ID | `TASK-015` |
| 阶段 | Gate 5 |
| 状态来源 | `docs/tasks/TODO.md` |
| 依赖 | `TASK-011`, `TASK-012`, `TASK-014` |
| 参考文档 | `docs/agent-identity-permission-api-spec.md`, `docs/agent-identity-permission-database-design.md` |
| 建议写入范围 | 审计与补偿相关的 `packages/audit/**`、`packages/application/**`、`apps/api/**`、异常任务查询逻辑 |
| 禁止改动范围 | 四份冻结基线文档、员工端页面、非补偿类前端交互 |

## 任务目标

补齐审计查询、失败任务查询和人工补偿重试接口，为后台管理提供支撑。

## 范围

- `GET /audit-records`
- `GET /admin/failed-tasks`
- `POST /admin/connector-tasks/{id}/retry`
- 审计补写与补偿操作记录

## 交付物

- 审计查询服务
- 异常任务查询服务
- 补偿重试接口

## 完成定义

- 管理员可查询一条完整申请链路
- IT 管理员可识别并重试失败任务
- 所有补偿操作都有审计记录

## 协作要求

- 前端后台任务应复用本任务 API，不绕过后端直接操作数据
