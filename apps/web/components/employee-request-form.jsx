"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { employeeRequestBrowserClient, getErrorMessage } from "../lib/employee-request-browser-client";
import { StatusPill } from "./status-pill";
import styles from "./employee-request-ui.module.css";

const STORAGE_KEY = "aisecurity.employee_request_context";
const DEFAULT_CONTEXT = {
  userId: "",
  agentId: "",
  delegationId: "",
  conversationId: "",
};

function readStoredContext() {
  if (typeof window === "undefined") {
    return DEFAULT_CONTEXT;
  }

  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    if (!value) {
      return DEFAULT_CONTEXT;
    }

    return { ...DEFAULT_CONTEXT, ...JSON.parse(value) };
  } catch {
    return DEFAULT_CONTEXT;
  }
}

function writeStoredContext(context) {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(context));
}

export function EmployeeRequestForm({
  apiClient = employeeRequestBrowserClient,
  initialContext = DEFAULT_CONTEXT,
}) {
  const [context, setContext] = useState(initialContext);
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setContext((current) => ({ ...current, ...readStoredContext() }));
  }, []);

  function updateContext(field, value) {
    setContext((current) => {
      const next = { ...current, [field]: value };
      writeStoredContext(next);
      return next;
    });
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    setResult(null);

    try {
      const payload = await apiClient.submitPermissionRequest({
        userId: context.userId.trim(),
        agentId: context.agentId.trim(),
        delegationId: context.delegationId.trim(),
        conversationId: context.conversationId.trim(),
        message: message.trim(),
      });
      setResult(payload.data);
    } catch (submitError) {
      setError(getErrorMessage(submitError));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className={styles.surfaceCard}>
      <h2 className={styles.sectionTitle}>提交新的权限申请</h2>
      <p className={styles.sectionHint}>
        页面会把员工身份上下文、自然语言申请和委托凭证一起提交到后端接口，并尝试立即同步评估结果。
      </p>

      <form onSubmit={handleSubmit}>
        <div className={styles.contextGrid}>
          <label className={styles.fieldLabel}>
            <span>员工 user_id</span>
            <input
              className={styles.input}
              name="user_id"
              value={context.userId}
              onChange={(event) => updateContext("userId", event.target.value)}
              placeholder="例如 user_001"
              required
            />
          </label>
          <label className={styles.fieldLabel}>
            <span>Agent ID</span>
            <input
              className={styles.input}
              name="agent_id"
              value={context.agentId}
              onChange={(event) => updateContext("agentId", event.target.value)}
              placeholder="例如 agent_perm_assistant_v1"
              required
            />
          </label>
          <label className={styles.fieldLabel}>
            <span>Delegation ID</span>
            <input
              className={styles.input}
              name="delegation_id"
              value={context.delegationId}
              onChange={(event) => updateContext("delegationId", event.target.value)}
              placeholder="例如 dlg_123"
              required
            />
          </label>
          <label className={styles.fieldLabel}>
            <span>Conversation ID（可选）</span>
            <input
              className={styles.input}
              name="conversation_id"
              value={context.conversationId}
              onChange={(event) => updateContext("conversationId", event.target.value)}
              placeholder="例如 conv_001"
            />
          </label>
          <label className={`${styles.fieldLabel} ${styles.contextWide}`}>
            <span>自然语言申请</span>
            <textarea
              className={styles.textarea}
              name="message"
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              placeholder="例如：我需要查看销售部 Q3 报表，但不需要修改权限。"
              required
            />
          </label>
        </div>

        <div className={styles.actions}>
          <button className={styles.button} type="submit" disabled={submitting}>
            {submitting ? "提交中..." : "提交申请"}
          </button>
          <Link className={styles.buttonGhost} href="/employee/requests">
            查看我的申请状态
          </Link>
        </div>
      </form>

      {error ? (
        <div className={styles.errorCallout} role="alert">
          <p className={styles.calloutTitle}>提交失败</p>
          <p className={styles.calloutText}>{error}</p>
        </div>
      ) : null}

      {result ? (
        <div className={styles.successCard}>
          <p className={styles.calloutTitle}>申请已提交</p>
          <p className={styles.calloutText}>
            申请单 <code>{result.permission_request_id}</code> 已创建，当前状态如下。
          </p>
          <div className={styles.statsGrid}>
            <div className={styles.statCard}>
              <span className={styles.statLabel}>申请状态</span>
              <StatusPill kind="request" value={result.request_status} />
            </div>
            <div className={styles.statCard}>
              <span className={styles.statLabel}>审批状态</span>
              <StatusPill
                kind="approval"
                value={result.evaluation?.approval_status ?? result.evaluation_error?.code ?? "NotRequired"}
              />
            </div>
            <div className={styles.statCard}>
              <span className={styles.statLabel}>风险等级</span>
              <span className={styles.summaryValue}>{result.evaluation?.risk_level ?? "待评估"}</span>
            </div>
          </div>
          {result.evaluation_error ? (
            <div className={styles.callout}>
              <p className={styles.calloutTitle}>评估结果暂未同步</p>
              <p className={styles.calloutText}>
                已成功创建申请，但评估步骤返回了 <code>{result.evaluation_error.code}</code>。详情页仍可继续查看原始状态，并可再次触发同步。
              </p>
            </div>
          ) : null}
          <div className={styles.linkRow}>
            <Link
              className={styles.inlineLink}
              href={`/employee/requests/${result.permission_request_id}`}
            >
              打开申请详情
            </Link>
            <Link className={styles.inlineLink} href="/employee/requests">
              打开状态列表
            </Link>
          </div>
        </div>
      ) : null}
    </section>
  );
}
