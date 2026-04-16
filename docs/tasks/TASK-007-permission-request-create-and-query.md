# TASK-007 申请单创建与查询 API

| 字段 | 内容 |
| --- | --- |
| Task ID | `TASK-007` |
| 阶段 | Gate 1 |
| 状态来源 | `docs/tasks/TODO.md` |
| 依赖 | `TASK-005`, `TASK-006` |
| 参考文档 | `docs/agent-identity-permission-api-spec.md`, `docs/agent-identity-permission-state-machine.md` |
| 建议写入范围 | 申请单相关的 `packages/application/**`、`apps/api/**`、`packages/infrastructure/**` 以及相关测试 |
| 禁止改动范围 | 四份冻结基线文档、策略引擎、审批连接器、前端页面 |

## 任务目标

实现自然语言申请提交、详情查询和列表查询，建立申请主链路的起点。

## 范围

- `POST /permission-requests`
- `GET /permission-requests/{id}`
- `GET /permission-requests`
- 原始文本持久化
- 申请主状态初始化
- 申请事件落库

## 交付物

- 申请单服务
- 创建、详情、列表 API
- 相关测试

## 完成定义

- 用户可以提交自然语言申请
- 申请单保存 `raw_text`、`agent_id`、`delegation_id`
- 状态变化通过应用层和事件表完成

## 协作要求

- 禁止在控制器中直接写 SQL 改状态
