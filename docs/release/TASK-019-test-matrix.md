# TASK-019 测试矩阵

- 任务：`TASK-019`
- 日期：`2026-04-19`
- 结论：后端单元、关键集成、Mock Feishu 集成、5 个核心 E2E 场景、前端测试与构建均已执行；结果整体通过。

## 1. 单元测试矩阵

| 类别 | 入口 | 覆盖重点 | 结果 |
| --- | --- | --- | --- |
| Domain / 状态枚举 | `./.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py' -v` | `tests/unit/test_domain_enums.py` 校验 `request_status` / `approval_status` / `grant_status` / `session_status` / `task_status` 与文档一致 | `58/58 PASS` |
| Policy / 最小权限映射 | 同上 | `tests/unit/test_policy_engine.py` 校验同部门只读、跨部门、高敏资源、兜底人工复核路径 | `PASS` |
| Provisioning 幂等 / 重试 | 同上 | `tests/unit/test_provisioning_service.py` 校验重复开通不重复建任务、失败后 `force_retry` 可重试 | `PASS` |
| Session revoke / Agent disable | 同上 | `tests/unit/test_session_authority_service.py` 校验人工撤销、Agent 停用联动撤销、撤销成功/失败 | `PASS` |
| Grant lifecycle | 同上 | `tests/unit/test_grant_lifecycle_service.py` 校验即将过期、到期回收、续期闭环 | `PASS` |

## 2. 集成测试矩阵

| 类别 | 入口 | 覆盖重点 | 结果 |
| --- | --- | --- | --- |
| 审批回调安全与幂等 | 嵌入式 PostgreSQL + `tests.integration.test_approval_callback_api` | 审批通过、审批驳回、重复回调幂等、无效签名拒绝、缺失审批记录返回 404 | `5/5 PASS` |
| 开通接口与失败写回 | 嵌入式 PostgreSQL + `tests.integration.test_grant_provision_api` | 开通进入 `Provisioning`、直接生效进入 `Active`、连接器不可用时失败写回 | `3/3 PASS` |
| 撤销链路 API | 嵌入式 PostgreSQL + `tests.integration.test_session_revoke_api` | 人工撤销后 `session/grant/request` 状态推进及撤销任务创建 | `1/1 PASS` |
| 生命周期 Worker | 嵌入式 PostgreSQL + `tests.integration.test_worker_grant_lifecycle_task` | 标记 `Expiring` 与到期转 `Expired` | `1/1 PASS` |
| 撤销 Worker | 嵌入式 PostgreSQL + `tests.integration.test_worker_session_revoke_task` | 撤销成功进入 `Revoked`、撤销失败进入 `SyncFailed` / `RevokeFailed` | `2/2 PASS` |
| 审计与补偿 API | 嵌入式 PostgreSQL + `tests.integration.test_audit_admin_api` | 审计查询、分页、失败任务检索、补偿重试允许/拒绝 | `5/5 PASS` |
| Mock Feishu 端到端集成 | `./.venv/bin/python scripts/run_task_018_tests.py` 的集成部分 | 审批通过、驳回、重复回调、开通失败后重试、已批准未生效、到期回收、Agent 停用撤销、撤销失败补偿 | `8/8 PASS` |

## 3. 核心 E2E 场景矩阵

| 场景 | 用例 | 结果 |
| --- | --- | --- |
| 同部门员工申请销售 Q3 报表只读权限 | `tests/e2e/test_permission_workflows_e2e.py::test_same_department_employee_gets_sales_q3_read_only_access` | `PASS` |
| 跨部门员工申请高敏资源访问 | `tests/e2e/test_permission_workflows_e2e.py::test_cross_department_high_sensitive_access_requires_approval_and_can_complete` | `PASS` |
| 审批通过但飞书开通失败 | `tests/e2e/test_permission_workflows_e2e.py::test_approval_passed_but_feishu_provision_failed` | `PASS` |
| 授权到期后自动回收 | `tests/e2e/test_permission_workflows_e2e.py::test_authorization_expires_and_is_reclaimed_automatically` | `PASS` |
| Agent 被停用后撤销生效 | `tests/e2e/test_permission_workflows_e2e.py::test_agent_disable_triggers_revoke_and_takes_effect` | `PASS` |

## 4. 前端验证矩阵

| 类别 | 入口 | 说明 | 结果 |
| --- | --- | --- | --- |
| Web 组件与 route 测试 | `TMPDIR=/tmp PATH=/home/xiaotaosen/.vscode-server/bin/560a9dba96f961efea7b1612916f89e5d5d4d679:$PATH ../../node_modules/.bin/vitest run` | 覆盖员工端申请/列表/详情、管理端审计/失败任务/retry，以及伪造浏览器身份参数被 route 忽略、评估走受控服务端 hook | `11/11 PASS` |
| Web lint | `TMPDIR=/tmp PATH=/home/xiaotaosen/.vscode-server/bin/560a9dba96f961efea7b1612916f89e5d5d4d679:$PATH ../../node_modules/.bin/eslint .` | 管理台与员工端页面静态检查 | `PASS` |
| Web build | `PATH=/home/xiaotaosen/.vscode-server/bin/560a9dba96f961efea7b1612916f89e5d5d4d679:$PATH ../../node_modules/.bin/next build` | Next.js 生产构建成功，静态/动态路由可生成 | `PASS` |

## 5. 已执行命令

```bash
./.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py' -v
TMPDIR=/tmp PATH=/home/xiaotaosen/.vscode-server/bin/560a9dba96f961efea7b1612916f89e5d5d4d679:$PATH ../../node_modules/.bin/vitest run
TMPDIR=/tmp PATH=/home/xiaotaosen/.vscode-server/bin/560a9dba96f961efea7b1612916f89e5d5d4d679:$PATH ../../node_modules/.bin/eslint .
PATH=/home/xiaotaosen/.vscode-server/bin/560a9dba96f961efea7b1612916f89e5d5d4d679:$PATH ../../node_modules/.bin/next build
./.venv/bin/python scripts/run_task_018_tests.py
./.venv/bin/python -m unittest \
  tests.integration.test_approval_callback_api \
  tests.integration.test_grant_provision_api \
  tests.integration.test_session_revoke_api \
  tests.integration.test_worker_grant_lifecycle_task \
  tests.integration.test_worker_session_revoke_task \
  tests.integration.test_audit_admin_api \
  -v
```
