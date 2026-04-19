"use client";

import { useEffect, useState } from "react";

import { adminBrowserClient, getAdminErrorMessage } from "../lib/admin-browser-client";
import { formatDateTime, formatValue } from "../lib/admin-presenters";
import styles from "./employee-request-ui.module.css";

const PAGE_SIZE = 10;
const DEFAULT_AUTH_CONTEXT = {
  userId: "security_admin_001",
  operatorType: "SecurityAdmin",
  source: "dev_stub",
};

function getContextDescription(authContext) {
  if (authContext.source === "dev_stub") {
    return "当前页面使用 Web 服务端受控的开发 stub 身份访问后台，页面输入不会决定真实管理员身份。";
  }
  return "当前页面使用服务端会话或统一身份注入层提供的管理员身份访问后台。";
}

export function AdminAuditConsole({
  apiClient = adminBrowserClient,
  authContext = DEFAULT_AUTH_CONTEXT,
}) {
  const [requestId, setRequestId] = useState("");
  const [eventType, setEventType] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [items, setItems] = useState([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);

  async function loadAuditRecords(nextPage = 1) {
    setLoading(true);
    setError("");

    try {
      const payload = await apiClient.listAuditRecords({
        requestId: requestId.trim(),
        eventType: eventType.trim(),
        page: String(nextPage),
        pageSize: String(PAGE_SIZE),
      });
      setItems(payload.data.items);
      setPage(payload.data.page);
      setTotal(payload.data.total);
    } catch (loadError) {
      setError(getAdminErrorMessage(loadError));
      setItems([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let cancelled = false;

    async function loadInitialAuditRecords() {
      try {
        const payload = await apiClient.listAuditRecords({
          requestId: "",
          eventType: "",
          page: "1",
          pageSize: String(PAGE_SIZE),
        });

        if (cancelled) {
          return;
        }

        setError("");
        setItems(payload.data.items);
        setPage(payload.data.page);
        setTotal(payload.data.total);
      } catch (loadError) {
        if (cancelled) {
          return;
        }

        setError(getAdminErrorMessage(loadError));
        setItems([]);
        setTotal(0);
      }
    }

    void loadInitialAuditRecords();

    return () => {
      cancelled = true;
    };
  }, [apiClient]);

  const hasNextPage = page * PAGE_SIZE < total;

  return (
    <section className={styles.tableCard}>
      <div className={styles.callout}>
        <p className={styles.calloutTitle}>当前管理上下文</p>
        <p className={styles.calloutText}>
          当前以 <code>{authContext.userId}</code> / <code>{authContext.operatorType}</code> 执行查询。
          {getContextDescription(authContext)}
        </p>
      </div>

      <div className={styles.listHeader}>
        <div>
          <h2 className={styles.sectionTitle}>审计记录查询</h2>
          <p className={styles.listMeta}>
            支持按 <code>request_id</code> 与 <code>event_type</code> 查询，并展示核心上下文。
          </p>
        </div>
        <button
          className={styles.buttonGhost}
          type="button"
          onClick={() => loadAuditRecords(1)}
          disabled={loading}
        >
          {loading ? "查询中..." : "执行查询"}
        </button>
      </div>

      <div className={styles.fieldGrid}>
        <div className={styles.detailItem}>
          <span className={styles.detailTerm}>管理员 user_id</span>
          <p className={`${styles.detailValue} ${styles.codeValue}`}>{authContext.userId}</p>
        </div>
        <div className={styles.detailItem}>
          <span className={styles.detailTerm}>操作人类型</span>
          <p className={`${styles.detailValue} ${styles.codeValue}`}>
            {authContext.operatorType}
          </p>
        </div>
        <label className={styles.fieldLabel}>
          <span>request_id</span>
          <input
            className={styles.input}
            value={requestId}
            onChange={(event) => setRequestId(event.target.value)}
            placeholder="例如 req_audit_chain_001"
          />
        </label>
        <label className={styles.fieldLabel}>
          <span>event_type</span>
          <input
            className={styles.input}
            value={eventType}
            onChange={(event) => setEventType(event.target.value)}
            placeholder="例如 grant.provisioned"
          />
        </label>
      </div>

      {error ? (
        <div className={styles.errorCallout} role="alert">
          <p className={styles.calloutTitle}>查询失败</p>
          <p className={styles.calloutText}>{error}</p>
        </div>
      ) : null}

      {!error && !items.length ? (
        <div className={styles.emptyState}>
          <p className={styles.calloutTitle}>暂无审计记录</p>
          <p className={styles.calloutText}>可以直接按条件检索审计链路，无需在页面手工填写管理员身份。</p>
        </div>
      ) : null}

      {items.length ? (
        <>
          <div className={styles.requestList}>
            {items.map((item) => (
              <article key={item.audit_id} className={styles.requestRow}>
                <div>
                  <h3 className={styles.requestTitle}>{item.event_type}</h3>
                  <p className={styles.requestSnippet}>
                    request: <code>{formatValue(item.request_id)}</code> / actor:{" "}
                    <code>{formatValue(item.actor_id)}</code>
                  </p>
                  <div className={styles.requestMeta}>
                    <span>actor_type：{formatValue(item.actor_type)}</span>
                    <span>result：{formatValue(item.result)}</span>
                    <span>created_at：{formatDateTime(item.created_at)}</span>
                  </div>
                </div>

                <div>
                  <p className={styles.requestSnippet}>
                    request_status：{formatValue(item.request?.request_status)} / grant_status：
                    {formatValue(item.grant?.grant_status)}
                  </p>
                  <p className={styles.requestSnippet}>
                    connector_task：{formatValue(item.connector_task?.task_id)} / approval：
                    {formatValue(item.approval_record?.approval_id)}
                  </p>
                </div>

                <div className={styles.requestMeta}>
                  <span>{formatValue(item.audit_id)}</span>
                </div>
              </article>
            ))}
          </div>

          <div className={styles.actions}>
            <button
              className={styles.buttonGhost}
              type="button"
              onClick={() => loadAuditRecords(page - 1)}
              disabled={loading || page <= 1}
            >
              上一页
            </button>
            <button
              className={styles.buttonGhost}
              type="button"
              onClick={() => loadAuditRecords(page + 1)}
              disabled={loading || !hasNextPage}
            >
              下一页
            </button>
            <p className={styles.listMeta}>
              第 {page} 页，共 {total} 条记录。
            </p>
          </div>
        </>
      ) : null}
    </section>
  );
}
