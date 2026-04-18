import Link from "next/link";

import { AdminShell } from "../../components/admin-shell";
import styles from "../../components/employee-request-ui.module.css";

export default function AdminHomePage() {
  return (
    <AdminShell
      eyebrow="Admin Console"
      title="管理后台最小联调入口"
      description="聚焦审计查询、失败任务定位和补偿 retry 三条最小管理路径，方便直接对接 TASK-015 的后台 API。"
      activeHref="/admin"
      aside={
        <>
          <h2 className={styles.sectionTitle}>使用建议</h2>
          <ul className={styles.helperList}>
            <li>先在审计页按 request_id 或 event_type 拉一条链路，确认失败发生位置。</li>
            <li>再到失败任务页定位 task_type、task_status、grant_id 与最近错误信息。</li>
            <li>最后在补偿页确认任务状态、错误原因与操作提示后，再发起 retry。</li>
          </ul>
        </>
      }
    >
      <section className={styles.gridTwo}>
        <article className={styles.surfaceCard}>
          <h2 className={styles.sectionTitle}>审计查询页</h2>
          <p className={styles.sectionHint}>
            支持按 <code>request_id</code> 和 <code>event_type</code> 检索审计记录，并做基础分页展示。
          </p>
          <div className={styles.linkRow}>
            <Link className={styles.button} href="/admin/audit">
              打开审计查询
            </Link>
          </div>
        </article>

        <article className={styles.surfaceCard}>
          <h2 className={styles.sectionTitle}>失败任务列表页</h2>
          <p className={styles.sectionHint}>
            快速查看 <code>task_type</code>、<code>task_status</code>、关联
            <code>request_id</code>/<code>grant_id</code> 与最近错误。
          </p>
          <div className={styles.linkRow}>
            <Link className={styles.buttonGhost} href="/admin/failed-tasks">
              打开失败任务
            </Link>
            <Link className={styles.buttonGhost} href="/admin/compensation">
              打开补偿页
            </Link>
          </div>
        </article>
      </section>
    </AdminShell>
  );
}
