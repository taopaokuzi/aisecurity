import { getStatusMeta } from "../lib/employee-request-presenters";
import styles from "./employee-request-ui.module.css";

export function StatusPill({ kind, value }) {
  const meta = getStatusMeta(kind, value);
  const toneClassName = styles[`tone${meta.tone.charAt(0).toUpperCase()}${meta.tone.slice(1)}`];

  return (
    <span className={`${styles.badge} ${toneClassName}`}>
      <span>{meta.label}</span>
      {value ? <span className={styles.badgeRaw}>{value}</span> : null}
    </span>
  );
}
