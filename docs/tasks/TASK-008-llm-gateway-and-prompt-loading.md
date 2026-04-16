# TASK-008 LLM Gateway 与 Prompt 装载

| 字段 | 内容 |
| --- | --- |
| Task ID | `TASK-008` |
| 阶段 | Gate 2 |
| 状态来源 | `docs/tasks/TODO.md` |
| 依赖 | `TASK-001`, `TASK-002` |
| 参考文档 | `docs/agent-identity-permission-development-guide.md`, `docs/agent-identity-permission-api-spec.md` |
| 建议写入范围 | `packages/prompts/**`、LLM 基础设施封装、模型调用配置与测试 |
| 禁止改动范围 | 四份冻结基线文档、最终授权决策逻辑、前端页面 |

## 任务目标

建立统一的 LLM 调用封装和 Prompt 模板加载机制，为后续评估流程服务。

## 范围

- `llm_gateway` 封装
- `packages/prompts` 模板读取
- 模型、超时、重试等基础配置
- 调用日志与错误处理边界

## 交付物

- 可复用的 LLM 客户端封装
- Prompt 加载工具
- 配置样例与基础测试

## 完成定义

- 业务代码无需直接调用裸模型 SDK
- Prompt 不散落在业务代码内
- 异常情况有明确返回和日志

## 协作要求

- 不在本任务中决定最终授权，只提供解析能力基础设施
