import Link from "next/link";

import styles from "./employee-request-ui.module.css";

const NAV_ITEMS = [
  { href: "/admin", label: "后台入口" },
  { href: "/admin/audit", label: "审计查询" },
  { href: "/admin/failed-tasks", label: "失败任务" },
  { href: "/admin/compensation", label: "补偿重试" },
];

export function AdminShell({
  eyebrow,
  title,
  description,
  activeHref,
  aside,
  children,
}) {
  return (
    <main className={styles.shell}>
      <section className={styles.masthead}>
        <div className={styles.heroCard}>
          <p className={styles.eyebrow}>{eyebrow}</p>
          <h1 className={styles.title}>{title}</h1>
          <p className={styles.description}>{description}</p>
          <nav className={styles.nav} aria-label="管理后台页面导航">
            {NAV_ITEMS.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={`${styles.navLink} ${
                  activeHref === item.href ? styles.navLinkActive : ""
                }`}
              >
                {item.label}
              </Link>
            ))}
          </nav>
        </div>
        <aside className={styles.asideCard}>{aside}</aside>
      </section>
      <div className={styles.pageBody}>{children}</div>
    </main>
  );
}
