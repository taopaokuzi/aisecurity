import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AdminAuditConsole } from "./admin-audit-console";

describe("AdminAuditConsole", () => {
  it("queries and renders audit records", async () => {
    window.localStorage.setItem(
      "aisecurity.admin_console_context",
      JSON.stringify({ userId: "sec_admin_001", operatorType: "SecurityAdmin" })
    );

    const apiClient = {
      listAuditRecords: vi.fn().mockResolvedValue({
        data: {
          page: 1,
          total: 1,
          items: [
            {
              audit_id: "aud_001",
              request_id: "req_001",
              event_type: "grant.provisioned",
              actor_type: "System",
              actor_id: "worker_01",
              result: "Success",
              created_at: "2026-04-18T08:00:00Z",
              request: { request_status: "Active" },
              grant: { grant_status: "Active" },
              connector_task: { task_id: "ctk_001" },
              approval_record: { approval_id: "apr_001" },
            },
          ],
        },
      }),
    };

    render(<AdminAuditConsole apiClient={apiClient} />);

    await waitFor(() => {
      expect(apiClient.listAuditRecords).toHaveBeenCalled();
    });

    fireEvent.change(screen.getByPlaceholderText("例如 req_audit_chain_001"), {
      target: { value: "req_001" },
    });
    fireEvent.click(screen.getByRole("button", { name: "执行查询" }));

    await waitFor(() => {
      expect(apiClient.listAuditRecords).toHaveBeenLastCalledWith(
        expect.objectContaining({
          userId: "sec_admin_001",
          operatorType: "SecurityAdmin",
          requestId: "req_001",
        })
      );
    });

    expect(await screen.findByText("grant.provisioned")).toBeInTheDocument();
    expect(screen.getByText(/request: /)).toBeInTheDocument();
    expect(screen.getByText(/result：Success/)).toBeInTheDocument();
  });
});
