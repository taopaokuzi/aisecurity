# TASK-004 领域枚举与共享模型

| 字段 | 内容 |
| --- | --- |
| Task ID | `TASK-004` |
| 阶段 | Gate 1 |
| 状态来源 | `docs/tasks/TODO.md` |
| 依赖 | `TASK-001`, `TASK-002` |
| 参考文档 | `docs/agent-identity-permission-database-design.md`, `docs/agent-identity-permission-state-machine.md`, `docs/agent-identity-permission-api-spec.md` |
| 建议写入范围 | `packages/domain/**`、共享常量、共享 schema、统一错误码定义 |
| 禁止改动范围 | 四份冻结基线文档、前端页面、外部连接器具体实现 |

## 任务目标

把状态机、核心实体、错误码和通用数据结构沉淀到共享领域层，作为后续 API、Worker、Policy 的统一依赖。

## 范围

- `packages/domain` 中定义状态枚举
- 定义用户、Agent、委托、申请单、审批、授权、会话、审计的核心模型
- 定义统一错误码和常量
- 定义跨模块 DTO 或 Schema 基础结构

## 交付物

- 统一枚举与模型定义
- 状态值与数据库/接口文档一致
- 共享错误码定义

## 完成定义

- 后续任务不再自行发明状态字符串
- 关键状态机枚举与文档一致
- 至少有单元测试验证关键枚举和模型约束

## 协作要求

- 后续线程修改状态值前必须回看本任务产物
