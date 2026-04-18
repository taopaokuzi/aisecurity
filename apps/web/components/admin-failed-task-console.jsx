"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { adminBrowserClient, getAdminErrorMessage } from "../lib/admin-browser-client";
import { formatDateTime, formatValue, getFailureSummary } from "../lib/admin-presenters";
import { StatusPill } from "./status-pill";
import styles from "./employee-request-ui.module.css";

const STORAGE_KEY = "aisecurity.admin_console_context";
const PAGE_SIZE = 10;

function readAdminContext() {
  if (typeof window === "undefined") {
    return { userId: "", operatorType: "ITAdmin" };
  }

  try {
    const parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}");
    return {
      userId: parsed.userId ?? "",
      operatorType: parsed.operatorType ?? "ITAdmin",
    };
  } catch {
    return { userId: "", operatorType: "ITAdmin" };
  }
}

function persistAdminContext(nextContext) {
  if (typeof window === "undefined") {
    return;
  }

  try {
    const current = readAdminContext();
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        ...current,
        ...nextContext,
      })
    );
  } catch {
    // Ignore storage failures and keep the UI interactive.
  }
}

export function AdminFailedTaskConsole({ apiClient = adminBrowserClient }) {
  const [userId, setUserId] = useState("");
  const [operatorType, setOperatorType] = useState("ITAdmin");
  const [taskType, setTaskType] = useState("");
  const [taskStatus, setTaskStatus] = useState("");
  const [requestId, setRequestId] = useState("");
  const [grantId, setGrantId] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [items, setItems] = useState([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);

  async function loadFailedTasks(nextPage = 1, nextUserId = userId, nextOperatorType = operatorType) {
    if (!nextUserId.trim()) {
      setError("请先填写管理员 user_id，再查询失败任务。");
      setItems([]);
      setTotal(0);
      return;
    }

    setLoading(true);
    setError("");

    try {
      const payload = await apiClient.listFailedTasks({
        userId: nextUserId.trim(),
        operatorType: nextOperatorType,
        taskType,
        taskStatus,
        requestId,
        grantId,
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
    const context = readAdminContext();
    setUserId(context.userId);
    setOperatorType(context.operatorType);
    if (!context.userId) {
      return;
    }

    let cancelled = false;

    async function loadInitialFailedTasks() {
      try {
        const payload = await apiClient.listFailedTasks({
          userId: context.userId,
          operatorType: context.operatorType,
          taskType: "",
          taskStatus: "",
          requestId: "",
          grantId: "",
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

    void loadInitialFailedTasks();

    return () => {
      cancelled = true;
    };
  }, [apiClient]);

  const hasNextPage = page * PAGE_SIZE < total;

  return (
    <section className={styles.tableCard}>
      <div className={styles.listHeader}>
        <div>
          <h2 className={styles.sectionTitle}>失败任务列表</h2>
          <p className={styles.listMeta}>
            展示 <code>task_type</code>、<code>task_status</code>、关联
            <code>request_id</code>/<code>grant_id</code> 与最近错误信息。
          </p>
        </div>
        <button
          className={styles.buttonGhost}
          type="button"
          onClick={() => loadFailedTasks(1)}
          disabled={loading}
        >
          {loading ? "查询中..." : "刷新列表"}
        </button>
      </div>

      <div className={styles.fieldGrid}>
        <label className={styles.fieldLabel}>
          <span>管理员 user_id</span>
          <input
            className={styles.input}
            value={userId}
            onChange={(event) => {
              setUserId(event.target.value);
              persistAdminContext({ userId: event.target.value });
            }}
            placeholder="例如 it_admin_001"
          />
        </label>
        <label className={styles.fieldLabel}>
          <span>操作人类型</span>
          <select
            className={styles.select}
            value={operatorType}
            onChange={(event) => {
              setOperatorType(event.target.value);
              persistAdminContext({ operatorType: event.target.value });
            }}
          >
            <option value="ITAdmin">ITAdmin</option>
            <option value="SecurityAdmin">SecurityAdmin</option>
          </select>
        </label>
        <label className={styles.fieldLabel}>
          <span>task_type</span>
          <select
            className={styles.select}
            value={taskType}
            onChange={(event) => setTaskType(event.target.value)}
          >
            <option value="">全部</option>
            <option value="provision">provision</option>
            <option value="session_revoke">session_revoke</option>
            <option value="approval_callback">approval_callback</option>
          </select>
        </label>
        <label className={styles.fieldLabel}>
          <span>task_status</span>
          <input
            className={styles.input}
            value={taskStatus}
            onChange={(event) => setTaskStatus(event.target.value)}
            placeholder="例如 Failed"
          />
        </label>
        <label className={styles.fieldLabel}>
          <span>request_id</span>
          <input
            className={styles.input}
            value={requestId}
            onChange={(event) => setRequestId(event.target.value)}
            placeholder="例如 req_failed_provision_001"
          />
        </label>
        <label className={styles.fieldLabel}>
          <span>grant_id</span>
          <input
            className={styles.input}
            value={grantId}
            onChange={(event) => setGrantId(event.target.value)}
            placeholder="例如 grt_failed_provision_001"
          />
        </label>
      </div>

      {error ? (
        <div className={styles.errorCallout} role="alert">
          <p className={styles.calloutTitle}>列表查询失败</p>
          <p className={styles.calloutText}>{error}</p>
        </div>
      ) : null}

      {!error && !items.length ? (
        <div className={styles.emptyState}>
          <p className={styles.calloutTitle}>暂无失败任务</p>
          <p className={styles.calloutText}>填写管理员上下文后即可定位失败链路。</p>
        </div>
      ) : null}

      {items.length ? (
        <>
          <div className={styles.requestList}>
            {items.map((item) => (
              <article className={styles.requestRow} key={item.task_id}>
                <div>
                  <h3 className={styles.requestTitle}>{item.task_id}</h3>
                  <p className={styles.requestSnippet}>
                    task_type：<code>{formatValue(item.task_type)}</code> / source：
                    <code>{formatValue(item.task_source)}</code>
                  </p>
                  <div className={styles.requestMeta}>
                    <span>request_id：{formatValue(item.request_id)}</span>
                    <span>grant_id：{formatValue(item.grant_id)}</span>
                    <span>occurred_at：{formatDateTime(item.occurred_at)}</span>
                  </div>
                </div>

                <div>
                  <div className={styles.rowStatuses}>
                    <StatusPill kind="grant" value={item.request?.grant_status} />
                    <StatusPill kind="request" value={item.request?.request_status} />
                    <StatusPill kind="task" value={item.task_status} />
                  </div>
                  <p className={styles.requestSnippet}>最近错误：{getFailureSummary(item)}</p>
                </div>

                <Link className={styles.inlineLink} href="/admin/compensation">
                  打开补偿页
                </Link>
              </article>
            ))}
          </div>

          <div className={styles.actions}>
            <button
              className={styles.buttonGhost}
              type="button"
              onClick={() => loadFailedTasks(page - 1)}
              disabled={loading || page <= 1}
            >
              上一页
            </button>
            <button
              className={styles.buttonGhost}
              type="button"
              onClick={() => loadFailedTasks(page + 1)}
              disabled={loading || !hasNextPage}
            >
              下一页
            </button>
            <p className={styles.listMeta}>
              第 {page} 页，共 {total} 条任务。
            </p>
          </div>
        </>
      ) : null}
    </section>
  );
}
