# TASK-006 委托凭证用例与 API

| 字段 | 内容 |
| --- | --- |
| Task ID | `TASK-006` |
| 阶段 | Gate 1 |
| 状态来源 | `docs/tasks/TODO.md` |
| 依赖 | `TASK-005` |
| 参考文档 | `docs/agent-identity-permission-api-spec.md`, `docs/agent-identity-permission-database-design.md` |
| 建议写入范围 | 委托相关的 `packages/application/**`、`apps/api/**`、`packages/infrastructure/**` 以及委托测试文件 |
| 禁止改动范围 | 四份冻结基线文档、前端页面、审批回调和连接器实现 |

## 任务目标

完成委托凭证创建、查询和有效性校验，建立“用户 -> Agent”的可验证代办链。

## 范围

- `POST /delegations`
- `GET /delegations/{id}`
- 用户有效性检查
- Agent 启用状态检查
- 委托范围和过期时间校验
- 委托审计事件

## 交付物

- 委托服务
- 委托 API
- 委托校验单元测试与集成测试

## 完成定义

- 委托记录可正确持久化
- 无效委托不会被创建或放行
- 接口请求响应结构与 API 文档一致

## 协作要求

- 后续申请单创建任务应复用本任务的委托校验逻辑
