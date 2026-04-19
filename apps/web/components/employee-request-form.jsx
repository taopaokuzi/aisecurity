"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { employeeRequestBrowserClient, getErrorMessage } from "../lib/employee-request-browser-client";
import { StatusPill } from "./status-pill";
import styles from "./employee-request-ui.module.css";

const STORAGE_KEY = "aisecurity.employee_request_context";
const DEFAULT_CONTEXT = {
  agentId: "",
  delegationId: "",
  conversationId: "",
};

const DEFAULT_AUTH_CONTEXT = {
  userId: "user_001",
  operatorType: "User",
  source: "dev_stub",
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

    const parsed = JSON.parse(value);
    return {
      agentId: parsed.agentId ?? DEFAULT_CONTEXT.agentId,
      delegationId: parsed.delegationId ?? DEFAULT_CONTEXT.delegationId,
      conversationId: parsed.conversationId ?? DEFAULT_CONTEXT.conversationId,
    };
  } catch {
    return DEFAULT_CONTEXT;
  }
}

function writeStoredContext(context) {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({
      agentId: context.agentId,
      delegationId: context.delegationId,
      conversationId: context.conversationId,
    })
  );
}

export function EmployeeRequestForm({
  apiClient = employeeRequestBrowserClient,
  initialContext = DEFAULT_CONTEXT,
  authContext = DEFAULT_AUTH_CONTEXT,
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
        页面只展示当前已认证员工上下文；真正的用户身份由 Web 服务端受控注入，再把自然语言申请和委托凭证提交给后端。
      </p>

      <div className={styles.callout}>
        <p className={styles.calloutTitle}>当前员工上下文</p>
        <p className={styles.calloutText}>
          当前以 <code>{authContext.userId}</code> / <code>{authContext.operatorType}</code> 提交申请。
          {authContext.source === "dev_stub"
            ? " 这是 Web 服务端提供的受控开发 stub 身份，不接受页面手工覆盖。"
            : " 这是由服务端会话或统一身份注入层提供的已认证身份。"}
        </p>
      </div>

      <form onSubmit={handleSubmit}>
        <div className={styles.contextGrid}>
          <div className={styles.detailItem}>
            <span className={styles.detailTerm}>员工 user_id</span>
            <p className={`${styles.detailValue} ${styles.codeValue}`}>{authContext.userId}</p>
          </div>
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
                已成功创建申请，但服务端受控评估步骤返回了 <code>{result.evaluation_error.code}</code>。详情页仍可继续查看原始状态，并可再次触发同步。
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
