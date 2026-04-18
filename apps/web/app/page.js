import Link from "next/link";

import { EmployeeShell } from "../components/employee-shell";
import styles from "../components/employee-request-ui.module.css";

export default function HomePage() {
  return (
    <EmployeeShell
      eyebrow="Permission Web Console"
      title="员工端与管理后台入口"
      description="当前 Web 端已经覆盖员工申请链路与管理后台最小联调页面，既能提交申请，也能查询审计、失败任务和补偿 retry。"
      activeHref="/employee/requests/new"
      aside={
        <>
          <h2 className={styles.sectionTitle}>联调建议</h2>
          <ul className={styles.helperList}>
            <li>员工链路：先提交申请，再查看状态和详情。</li>
            <li>管理链路：先查审计，再看失败任务，最后按需发起 retry。</li>
            <li>管理后台所有操作都通过 TASK-015 的 API 联调，不写死后台数据。</li>
          </ul>
        </>
      }
    >
      <section className={styles.requestList}>
        <article className={styles.surfaceCard}>
          <h2 className={styles.sectionTitle}>发起权限申请</h2>
          <p className={styles.sectionHint}>
            适合直接录入自然语言需求，并把 `agent_id`、`delegation_id` 与会话上下文一起送到后端。
          </p>
          <div className={styles.linkRow}>
            <Link className={styles.button} href="/employee/requests/new">
              打开申请页
            </Link>
          </div>
        </article>
        <article className={styles.surfaceCard}>
          <h2 className={styles.sectionTitle}>查看申请状态</h2>
          <p className={styles.sectionHint}>
            适合按员工身份回查已提交申请，快速确认审批、评估和授权是否已经推进。
          </p>
          <div className={styles.linkRow}>
            <Link className={styles.buttonGhost} href="/employee/requests">
              打开状态页
            </Link>
          </div>
        </article>
        <article className={styles.surfaceCard}>
          <h2 className={styles.sectionTitle}>管理后台</h2>
          <p className={styles.sectionHint}>
            进入审计查询、失败任务列表和补偿 retry 页面，定位失败链路并执行最小补偿操作。
          </p>
          <div className={styles.linkRow}>
            <Link className={styles.buttonGhost} href="/admin">
              打开管理后台
            </Link>
          </div>
        </article>
      </section>
    </EmployeeShell>
  );
}
