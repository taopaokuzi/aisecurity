"use client";

import { useEffect, useState } from "react";

import { adminBrowserClient, getAdminErrorMessage } from "../lib/admin-browser-client";
import {
  formatDateTime,
  formatValue,
  getCompensationHint,
  getFailureSummary,
} from "../lib/admin-presenters";
import { StatusPill } from "./status-pill";
import styles from "./employee-request-ui.module.css";

const STORAGE_KEY = "aisecurity.admin_console_context";

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

export function AdminCompensationConsole({ apiClient = adminBrowserClient }) {
  const [userId, setUserId] = useState("");
  const [operatorType, setOperatorType] = useState("ITAdmin");
  const [requestId, setRequestId] = useState("");
  const [grantId, setGrantId] = useState("");
  const [loading, setLoading] = useState(false);
  const [retryingTaskId, setRetryingTaskId] = useState("");
  const [error, setError] = useState("");
  const [resultMessage, setResultMessage] = useState("");
  const [items, setItems] = useState([]);
  const [reasonByTaskId, setReasonByTaskId] = useState({});

  async function loadFailedTasks(nextUserId = userId, nextOperatorType = operatorType) {
    if (!nextUserId.trim()) {
      setError("请先填写管理员 user_id，再查询可补偿任务。");
      setItems([]);
      return;
    }

    setLoading(true);
    setError("");

    try {
      const payload = await apiClient.listFailedTasks({
        userId: nextUserId.trim(),
        operatorType: nextOperatorType,
        requestId,
        grantId,
        page: "1",
        pageSize: "20",
      });
      setItems(payload.data.items);
    } catch (loadError) {
      setError(getAdminErrorMessage(loadError));
      setItems([]);
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
          requestId: "",
          grantId: "",
          page: "1",
          pageSize: "20",
        });

        if (cancelled) {
          return;
        }

        setError("");
        setItems(payload.data.items);
      } catch (loadError) {
        if (cancelled) {
          return;
        }

        setError(getAdminErrorMessage(loadError));
        setItems([]);
      }
    }

    void loadInitialFailedTasks();

    return () => {
      cancelled = true;
    };
  }, [apiClient]);

  async function handleRetry(task) {
    const canRetry = task.retryable && operatorType === "ITAdmin";
    if (!canRetry) {
      setError(getCompensationHint(task, operatorType));
      setResultMessage("");
      return;
    }

    const reason =
      reasonByTaskId[task.task_id]?.trim() || "Manual retry from admin compensation console";

    const confirmed =
      typeof window === "undefined"
        ? true
        : window.confirm(
            `将为任务 ${task.task_id} 发起 retry。当前状态为 ${task.task_status}，请确认错误已排查。`
          );
    if (!confirmed) {
      return;
    }

    setRetryingTaskId(task.task_id);
    setError("");
    setResultMessage("");

    try {
      const payload = await apiClient.retryConnectorTask({
        taskId: task.task_id,
        userId: userId.trim(),
        operatorType,
        reason,
      });
      setResultMessage(
        `任务 ${payload.data.original_task_id} 已提交 retry，新任务 ${payload.data.retry_task_id ?? "未返回"}，当前 grant_status 为 ${payload.data.grant_status}。`
      );
      await loadFailedTasks();
    } catch (retryError) {
      setError(getAdminErrorMessage(retryError));
    } finally {
      setRetryingTaskId("");
    }
  }

  return (
    <section className={styles.tableCard}>
      <div className={styles.listHeader}>
        <div>
          <h2 className={styles.sectionTitle}>补偿 / Retry 操作</h2>
          <p className={styles.listMeta}>只对允许 retry 的失败任务开放操作，并在发起前做二次确认。</p>
        </div>
        <button
          className={styles.buttonGhost}
          type="button"
          onClick={() => loadFailedTasks()}
          disabled={loading}
        >
          {loading ? "查询中..." : "刷新待补偿任务"}
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
          <span>request_id</span>
          <input
            className={styles.input}
            value={requestId}
            onChange={(event) => setRequestId(event.target.value)}
            placeholder="可选，用于快速定位申请链路"
          />
        </label>
        <label className={styles.fieldLabel}>
          <span>grant_id</span>
          <input
            className={styles.input}
            value={grantId}
            onChange={(event) => setGrantId(event.target.value)}
            placeholder="可选，用于快速定位授权记录"
          />
        </label>
      </div>

      <div className={styles.callout}>
        <p className={styles.calloutTitle}>操作提示</p>
        <p className={styles.calloutText}>
          retry 只会调用后端补偿 API，不会在前端直接修改状态。执行前请确认连接器或外部依赖已经恢复。
        </p>
      </div>

      {error ? (
        <div className={styles.errorCallout} role="alert">
          <p className={styles.calloutTitle}>补偿操作失败</p>
          <p className={styles.calloutText}>{error}</p>
        </div>
      ) : null}

      {resultMessage ? (
        <div className={styles.successCard}>
          <p className={styles.calloutTitle}>补偿已提交</p>
          <p className={styles.calloutText}>{resultMessage}</p>
        </div>
      ) : null}

      {!error && !items.length ? (
        <div className={styles.emptyState}>
          <p className={styles.calloutTitle}>暂无可展示任务</p>
          <p className={styles.calloutText}>先填写管理员上下文，再加载失败任务并执行补偿。</p>
        </div>
      ) : null}

      {items.length ? (
        <div className={styles.requestList}>
          {items.map((item) => {
            const canRetry = item.retryable && operatorType === "ITAdmin";

            return (
              <article className={styles.requestRow} key={item.task_id}>
                <div>
                  <h3 className={styles.requestTitle}>{item.task_id}</h3>
                  <p className={styles.requestSnippet}>
                    task_type：<code>{formatValue(item.task_type)}</code> / request_id：
                    <code>{formatValue(item.request_id)}</code>
                  </p>
                  <div className={styles.requestMeta}>
                    <span>grant_id：{formatValue(item.grant_id)}</span>
                    <span>occurred_at：{formatDateTime(item.occurred_at)}</span>
                  </div>
                </div>

                <div>
                  <div className={styles.rowStatuses}>
                    <StatusPill kind="task" value={item.task_status} />
                    <StatusPill kind="request" value={item.request?.request_status} />
                    <StatusPill kind="grant" value={item.grant?.grant_status ?? item.request?.grant_status} />
                  </div>
                  <p className={styles.requestSnippet}>当前状态：{formatValue(item.task_status)}</p>
                  <p className={styles.requestSnippet}>最近错误：{getFailureSummary(item)}</p>
                  <p className={styles.requestSnippet}>{getCompensationHint(item, operatorType)}</p>
                  <label className={styles.fieldLabel}>
                    <span>retry reason</span>
                    <input
                      className={styles.input}
                      value={reasonByTaskId[item.task_id] ?? ""}
                      onChange={(event) =>
                        setReasonByTaskId((current) => ({
                          ...current,
                          [item.task_id]: event.target.value,
                        }))
                      }
                      placeholder="例如 Manual retry after connector recovery"
                    />
                  </label>
                </div>

                <button
                  className={canRetry ? styles.button : styles.buttonGhost}
                  type="button"
                  onClick={() => handleRetry(item)}
                  disabled={retryingTaskId === item.task_id || !canRetry}
                >
                  {retryingTaskId === item.task_id ? "提交中..." : "发起 retry"}
                </button>
              </article>
            );
          })}
        </div>
      ) : null}
    </section>
  );
}
