import { AdminAuditConsole } from "../../../components/admin-audit-console";
import { AdminShell } from "../../../components/admin-shell";
import styles from "../../../components/employee-request-ui.module.css";

export default function AdminAuditPage() {
  return (
    <AdminShell
      eyebrow="Audit Search"
      title="审计查询页"
      description="按 request_id、event_type 查询关键审计事件，并把 request / actor / result / created_at 一起展示出来。"
      activeHref="/admin/audit"
      aside={
        <>
          <h2 className={styles.sectionTitle}>查询范围</h2>
          <ul className={styles.helperList}>
            <li>request_id 适合回放单条申请链路。</li>
            <li>event_type 适合批量查看某一类事件，例如 grant.provisioned。</li>
            <li>分页结果按接口返回顺序展示，便于向后翻页排查。</li>
          </ul>
        </>
      }
    >
      <AdminAuditConsole />
    </AdminShell>
  );
}
