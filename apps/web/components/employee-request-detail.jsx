"use client";

import { useEffect, useState } from "react";

import { employeeRequestBrowserClient, getErrorMessage } from "../lib/employee-request-browser-client";
import {
  formatDateTime,
  formatValue,
  getRiskMeta,
  summarizeNextStep,
} from "../lib/employee-request-presenters";
import { StatusPill } from "./status-pill";
import styles from "./employee-request-ui.module.css";

const STORAGE_KEY = "aisecurity.employee_request_context";

function readUserId() {
  if (typeof window === "undefined") {
    return "";
  }

  try {
    return JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}").userId ?? "";
  } catch {
    return "";
  }
}

async function queryPermissionRequestDetail(apiClient, { requestId, userId }) {
  return apiClient.getPermissionRequestDetail({
    requestId,
    userId,
  });
}

export function EmployeeRequestDetail({
  requestId,
  apiClient = employeeRequestBrowserClient,
}) {
  const [userId, setUserId] = useState("");
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState("");
  const [detail, setDetail] = useState(null);

  useEffect(() => {
    const storedUserId = readUserId();
    if (storedUserId) {
      setUserId(storedUserId);
    }
  }, []);

  async function loadDetail(nextUserId = userId) {
    if (!nextUserId.trim()) {
      setError("请先填写员工 user_id，再查看申请详情。");
      setDetail(null);
      return;
    }

    setLoading(true);
    setError("");

    try {
      const payload = await queryPermissionRequestDetail(apiClient, {
        requestId,
        userId: nextUserId.trim(),
      });
      setDetail(payload.data);
    } catch (loadError) {
      setError(getErrorMessage(loadError));
      setDetail(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!userId) {
      return;
    }

    let cancelled = false;

    async function syncDetail() {
      setLoading(true);
      setError("");

      try {
        const payload = await queryPermissionRequestDetail(apiClient, {
          requestId,
          userId,
        });
        if (!cancelled) {
          setDetail(payload.data);
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(getErrorMessage(loadError));
          setDetail(null);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void syncDetail();

    return () => {
      cancelled = true;
    };
  }, [apiClient, requestId, userId]);

  async function handleSyncEvaluation() {
    setSyncing(true);
    setError("");

    try {
      await apiClient.evaluatePermissionRequest({ requestId });
      await loadDetail();
    } catch (syncError) {
      setError(getErrorMessage(syncError));
    } finally {
      setSyncing(false);
    }
  }

  function handleUserIdChange(value) {
    setUserId(value);
    if (typeof window !== "undefined") {
      try {
        const current = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}");
        window.localStorage.setItem(
          STORAGE_KEY,
          JSON.stringify({ ...current, userId: value })
        );
      } catch {
        // Ignore storage write failures and keep the UI interactive.
      }
    }
  }

  const request = detail?.request;
  const evaluation = detail?.evaluation;
  const riskMeta = getRiskMeta(evaluation?.risk_level ?? request?.risk_level);
  const canSyncEvaluation = Boolean(detail?.evaluation_error);

  return (
    <>
      <section className={styles.surfaceCard}>
        <div className={styles.listHeader}>
          <div>
            <h2 className={styles.sectionTitle}>申请详情</h2>
            <p className={styles.sectionHint}>
              详情页会同时读取申请详情与评估结果；如果评估尚未落库，可以在这里重新同步。
            </p>
          </div>
          <div className={styles.actions}>
            <button
              className={styles.buttonGhost}
              type="button"
              onClick={() => loadDetail()}
              disabled={loading}
            >
              {loading ? "刷新中..." : "刷新详情"}
            </button>
            <button
              className={styles.button}
              type="button"
              onClick={handleSyncEvaluation}
              disabled={syncing || !canSyncEvaluation}
            >
              {syncing ? "同步中..." : canSyncEvaluation ? "尝试同步评估" : "评估已同步"}
            </button>
          </div>
        </div>

        <div className={styles.fieldGrid}>
          <label className={styles.fieldLabel}>
            <span>员工 user_id</span>
            <input
              className={styles.input}
              value={userId}
              onChange={(event) => handleUserIdChange(event.target.value)}
              placeholder="例如 user_001"
            />
          </label>
          <div className={styles.detailItem}>
            <span className={styles.detailTerm}>申请单 ID</span>
            <p className={`${styles.detailValue} ${styles.codeValue}`}>{requestId}</p>
          </div>
        </div>

        {error ? (
          <div className={styles.errorCallout} role="alert">
            <p className={styles.calloutTitle}>详情读取失败</p>
            <p className={styles.calloutText}>{error}</p>
          </div>
        ) : null}
      </section>

      {detail ? (
        <div className={styles.gridTwo}>
          <section className={styles.timelineCard}>
            <h3 className={styles.sectionTitle}>状态总览</h3>
            <p className={styles.sectionHint}>
              {summarizeNextStep(
                request.request_status,
                request.approval_status,
                request.grant_status
              )}
            </p>
            <div className={styles.statsGrid}>
              <div className={styles.statCard}>
                <span className={styles.statLabel}>申请状态</span>
                <StatusPill kind="request" value={request.request_status} />
              </div>
              <div className={styles.statCard}>
                <span className={styles.statLabel}>审批状态</span>
                <StatusPill kind="approval" value={request.approval_status} />
              </div>
              <div className={styles.statCard}>
                <span className={styles.statLabel}>授权状态</span>
                <StatusPill kind="grant" value={request.grant_status} />
              </div>
            </div>

            <div className={styles.summaryGrid}>
              <div className={styles.summaryCard}>
                <span className={styles.statLabel}>建议权限</span>
                <span className={`${styles.summaryValue} ${styles.codeValue}`}>
                  {formatValue(evaluation?.suggested_permission ?? request.suggested_permission)}
                </span>
              </div>
              <div className={styles.summaryCard}>
                <span className={styles.statLabel}>风险等级</span>
                <span className={`${styles.summaryValue} ${styles[`tone${riskMeta.tone.charAt(0).toUpperCase()}${riskMeta.tone.slice(1)}`]}`}>
                  {riskMeta.label}
                </span>
              </div>
            </div>

            {detail.evaluation_error ? (
              <div className={styles.callout}>
                <p className={styles.calloutTitle}>评估信息暂未完全可用</p>
                <p className={styles.calloutText}>
                  后端返回 <code>{detail.evaluation_error.code}</code>，当前仍会优先展示已存在的申请字段。
                </p>
              </div>
            ) : null}
          </section>

          <section className={styles.timelineCard}>
            <h3 className={styles.sectionTitle}>联调说明</h3>
            <p className={styles.sectionHint}>
              当前员工端只覆盖最小可用链路，管理后台、补偿页面和后端编排不在本任务范围内。
            </p>
            <ul className={styles.helperList}>
              <li>申请创建使用员工上下文调用 `POST /permission-requests`。</li>
              <li>状态页按本人维度查询 `GET /permission-requests`。</li>
              <li>详情页同时读取 `GET /permission-requests/{'{id}'}` 和评估结果。</li>
              <li>如果评估尚未落库，可在详情页再次触发同步。</li>
            </ul>
          </section>
        </div>
      ) : null}

      {detail ? (
        <section className={styles.surfaceCard}>
          <h3 className={styles.sectionTitle}>申请与评估字段</h3>
          <div className={styles.detailGrid}>
            <div className={`${styles.detailItem} ${styles.detailItemWide}`}>
              <span className={styles.detailTerm}>raw_text</span>
              <p className={styles.detailValue}>{formatValue(request.raw_text)}</p>
            </div>
            <div className={styles.detailItem}>
              <span className={styles.detailTerm}>resource_key</span>
              <p className={`${styles.detailValue} ${styles.codeValue}`}>
                {formatValue(evaluation?.resource_key ?? request.resource_key)}
              </p>
            </div>
            <div className={styles.detailItem}>
              <span className={styles.detailTerm}>resource_type</span>
              <p className={styles.detailValue}>
                {formatValue(evaluation?.resource_type ?? request.resource_type)}
              </p>
            </div>
            <div className={styles.detailItem}>
              <span className={styles.detailTerm}>action</span>
              <p className={styles.detailValue}>{formatValue(evaluation?.action ?? request.action)}</p>
            </div>
            <div className={styles.detailItem}>
              <span className={styles.detailTerm}>requested_duration</span>
              <p className={styles.detailValue}>
                {formatValue(evaluation?.requested_duration ?? request.requested_duration)}
              </p>
            </div>
            <div className={styles.detailItem}>
              <span className={styles.detailTerm}>suggested_permission</span>
              <p className={`${styles.detailValue} ${styles.codeValue}`}>
                {formatValue(evaluation?.suggested_permission ?? request.suggested_permission)}
              </p>
            </div>
            <div className={styles.detailItem}>
              <span className={styles.detailTerm}>risk_level</span>
              <p className={styles.detailValue}>{riskMeta.label}</p>
            </div>
            <div className={styles.detailItem}>
              <span className={styles.detailTerm}>approval_status</span>
              <StatusPill kind="approval" value={request.approval_status} />
            </div>
            <div className={styles.detailItem}>
              <span className={styles.detailTerm}>grant_status</span>
              <StatusPill kind="grant" value={request.grant_status} />
            </div>
            <div className={styles.detailItem}>
              <span className={styles.detailTerm}>agent_id</span>
              <p className={`${styles.detailValue} ${styles.codeValue}`}>{formatValue(request.agent_id)}</p>
            </div>
            <div className={styles.detailItem}>
              <span className={styles.detailTerm}>delegation_id</span>
              <p className={`${styles.detailValue} ${styles.codeValue}`}>
                {formatValue(request.delegation_id)}
              </p>
            </div>
            <div className={styles.detailItem}>
              <span className={styles.detailTerm}>policy_version</span>
              <p className={styles.detailValue}>
                {formatValue(evaluation?.policy_version ?? request.policy_version)}
              </p>
            </div>
            <div className={styles.detailItem}>
              <span className={styles.detailTerm}>created_at</span>
              <p className={styles.detailValue}>{formatDateTime(request.created_at)}</p>
            </div>
            <div className={styles.detailItem}>
              <span className={styles.detailTerm}>updated_at</span>
              <p className={styles.detailValue}>{formatDateTime(request.updated_at)}</p>
            </div>
          </div>
        </section>
      ) : null}
    </>
  );
}
