# TASK-003 本地开发编排与配置加载

| 字段 | 内容 |
| --- | --- |
| Task ID | `TASK-003` |
| 阶段 | Gate 0 |
| 状态来源 | `docs/tasks/TODO.md` |
| 依赖 | `TASK-001`, `TASK-002` |
| 参考文档 | `docs/agent-identity-permission-development-guide.md`, `docs/agent-identity-permission-integration-spec.md` |
| 建议写入范围 | `docker/**`、根目录编排文件、`config/**`、`.env*` 样例、`README.md`、Alembic 初始化配置 |
| 禁止改动范围 | 四份冻结基线文档、业务 API 实现、前端业务页面逻辑 |

## 任务目标

建立本地开发与联调所需的容器编排、环境变量样例、配置加载和 README 启动说明。

## 范围

- `docker-compose` 或等价开发编排
- `.env.example` 或等价配置样例
- 配置文件目录与加载逻辑
- `README.md` 本地启动说明
- Alembic 初始化入口

## 交付物

- 本地可拉起 `postgres + redis + api + worker + web`
- 配置项有明确加载方式
- README 给出最小启动命令

## 完成定义

- 其他线程可以根据 README 在本地完成最小启动
- 环境变量名称与文档一致
- Alembic 命令链已可执行

## 协作要求

- 若某服务暂时未接真实外部系统，明确使用 mock 或 stub
