"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { employeeRequestBrowserClient, getErrorMessage } from "../lib/employee-request-browser-client";
import { formatDateTime, summarizeNextStep } from "../lib/employee-request-presenters";
import { StatusPill } from "./status-pill";
import styles from "./employee-request-ui.module.css";

const DEFAULT_AUTH_CONTEXT = {
  userId: "user_001",
  operatorType: "User",
  source: "dev_stub",
};

async function queryPermissionRequests(apiClient, { requestStatus, approvalStatus }) {
  return apiClient.listPermissionRequests({
    page: "1",
    pageSize: "20",
    requestStatus,
    approvalStatus,
  });
}

export function EmployeeRequestList({
  apiClient = employeeRequestBrowserClient,
  authContext = DEFAULT_AUTH_CONTEXT,
}) {
  const [requestStatus, setRequestStatus] = useState("");
  const [approvalStatus, setApprovalStatus] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);

  async function loadRequests() {
    setLoading(true);
    setError("");

    try {
      const payload = await queryPermissionRequests(apiClient, {
        requestStatus,
        approvalStatus,
      });
      setItems(payload.data.items);
      setTotal(payload.data.total);
    } catch (loadError) {
      setError(getErrorMessage(loadError));
      setItems([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let cancelled = false;

    async function syncRequests() {
      setLoading(true);
      setError("");

      try {
        const payload = await queryPermissionRequests(apiClient, {
          requestStatus,
          approvalStatus,
        });
        if (!cancelled) {
          setItems(payload.data.items);
          setTotal(payload.data.total);
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(getErrorMessage(loadError));
          setItems([]);
          setTotal(0);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void syncRequests();

    return () => {
      cancelled = true;
    };
  }, [apiClient, approvalStatus, requestStatus]);

  return (
    <section className={styles.tableCard}>
      <div className={styles.callout}>
        <p className={styles.calloutTitle}>当前员工上下文</p>
        <p className={styles.calloutText}>
          当前以 <code>{authContext.userId}</code> / <code>{authContext.operatorType}</code> 查询本人申请。
          页面不会再通过手工输入 user_id 来决定真实查询身份。
        </p>
      </div>

      <div className={styles.listHeader}>
        <div>
          <h2 className={styles.sectionTitle}>我的申请状态</h2>
          <p className={styles.listMeta}>按员工维度查询本人申请，展示申请、审批和授权三条状态线。</p>
        </div>
        <button
          className={styles.buttonGhost}
          type="button"
          onClick={() => loadRequests()}
          disabled={loading}
        >
          {loading ? "刷新中..." : "刷新列表"}
        </button>
      </div>

      <div className={styles.fieldGrid}>
        <div className={styles.detailItem}>
          <span className={styles.detailTerm}>员工 user_id</span>
          <p className={`${styles.detailValue} ${styles.codeValue}`}>{authContext.userId}</p>
        </div>
        <label className={styles.fieldLabel}>
          <span>申请状态筛选</span>
          <select
            className={styles.select}
            value={requestStatus}
            onChange={(event) => setRequestStatus(event.target.value)}
          >
            <option value="">全部</option>
            <option value="Submitted">Submitted</option>
            <option value="PendingApproval">PendingApproval</option>
            <option value="Approved">Approved</option>
            <option value="Provisioning">Provisioning</option>
            <option value="Active">Active</option>
            <option value="Failed">Failed</option>
          </select>
        </label>
        <label className={styles.fieldLabel}>
          <span>审批状态筛选</span>
          <select
            className={styles.select}
            value={approvalStatus}
            onChange={(event) => setApprovalStatus(event.target.value)}
          >
            <option value="">全部</option>
            <option value="NotRequired">NotRequired</option>
            <option value="Pending">Pending</option>
            <option value="Approved">Approved</option>
            <option value="Rejected">Rejected</option>
          </select>
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
          <p className={styles.calloutTitle}>暂无可展示的申请</p>
          <p className={styles.calloutText}>当前筛选条件下没有查询到记录，可以先去发起一笔申请。</p>
        </div>
      ) : null}

      {items.length ? (
        <div className={styles.requestList}>
          {items.map((item) => (
            <article className={styles.requestRow} key={item.request_id}>
              <div>
                <h3 className={styles.requestTitle}>{item.request_id}</h3>
                <p className={styles.requestSnippet}>{item.raw_text}</p>
                <div className={styles.requestMeta}>
                  <span>创建时间：{formatDateTime(item.created_at)}</span>
                  <span>建议权限：{item.suggested_permission ?? "待评估"}</span>
                </div>
              </div>

              <div>
                <div className={styles.rowStatuses}>
                  <StatusPill kind="request" value={item.request_status} />
                  <StatusPill kind="approval" value={item.approval_status} />
                  <StatusPill kind="grant" value={item.grant_status} />
                </div>
                <p className={styles.requestSnippet}>
                  {summarizeNextStep(
                    item.request_status,
                    item.approval_status,
                    item.grant_status
                  )}
                </p>
              </div>

              <Link className={styles.inlineLink} href={`/employee/requests/${item.request_id}`}>
                查看详情
              </Link>
            </article>
          ))}
        </div>
      ) : null}

      {items.length ? (
        <p className={styles.listMeta}>共查询到 {total} 条记录。</p>
      ) : null}
    </section>
  );
}
