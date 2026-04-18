import Link from "next/link";

import { EmployeeShell } from "../components/employee-shell";
import styles from "../components/employee-request-ui.module.css";

export default function HomePage() {
  return (
    <EmployeeShell
      eyebrow="Employee Permission Center"
      title="员工端最小联调入口"
      description="当前 Web 端已经聚焦到员工申请、状态查询和详情查看三条最小可用路径，方便直接和后端权限申请接口联调。"
      activeHref="/employee/requests/new"
      aside={
        <>
          <h2 className={styles.sectionTitle}>联调建议</h2>
          <ul className={styles.helperList}>
            <li>先在申请页填写员工上下文并提交自然语言申请。</li>
            <li>再去状态页查看 `request_status / approval_status / grant_status`。</li>
            <li>最后到详情页核对建议权限、风险等级和资源信息。</li>
          </ul>
        </>
      }
    >
      <section className={styles.gridTwo}>
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
      </section>
    </EmployeeShell>
  );
}
