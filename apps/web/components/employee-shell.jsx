import Link from "next/link";

import styles from "./employee-request-ui.module.css";

const NAV_ITEMS = [
  { href: "/employee/requests/new", label: "发起申请" },
  { href: "/employee/requests", label: "申请状态" },
];

export function EmployeeShell({
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
          <nav className={styles.nav} aria-label="员工端页面导航">
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
