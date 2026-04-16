# TASK-002 运行时入口与健康检查

| 字段 | 内容 |
| --- | --- |
| Task ID | `TASK-002` |
| 阶段 | Gate 0 |
| 状态来源 | `docs/tasks/TODO.md` |
| 依赖 | `TASK-001` |
| 参考文档 | `docs/agent-identity-permission-development-guide.md`, `docs/agent-identity-permission-api-spec.md` |
| 建议写入范围 | `apps/api/**`、`apps/worker/**`、`apps/web/**` 的运行入口、健康检查和启动相关文件 |
| 禁止改动范围 | 四份冻结基线文档、数据库迁移文件、业务领域模型和策略规则实现 |

## 任务目标

建立 FastAPI、Celery Worker、Next.js 的最小运行入口，并提供健康检查能力。

## 范围

- `apps/api` 创建主应用入口与 `/health`
- `apps/worker` 创建 Celery 应用入口与任务注册机制
- `apps/web` 创建最小页面与运行入口
- 基础设置加载入口与启动脚本

## 交付物

- API 可启动并返回健康检查
- Worker 可启动并加载基础任务
- Web 可启动并展示最小页面

## 完成定义

- `api`、`worker`、`web` 至少能本地独立启动
- 健康检查接口可访问
- 运行入口不是空壳文件

## 协作要求

- 不在此任务中实现业务接口
- 完成后更新总表的可启动任务状态
