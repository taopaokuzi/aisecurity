import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AdminFailedTaskConsole } from "./admin-failed-task-console";

describe("AdminFailedTaskConsole", () => {
  it("loads and renders failed tasks", async () => {
    const apiClient = {
      listFailedTasks: vi.fn().mockResolvedValue({
        data: {
          page: 1,
          total: 1,
          items: [
            {
              task_id: "ctk_failed_001",
              task_source: "connector_task",
              task_type: "provision",
              task_status: "Failed",
              request_id: "req_failed_001",
              grant_id: "grt_failed_001",
              occurred_at: "2026-04-18T08:00:00Z",
              failure_reason: "Connector timeout",
              retryable: true,
              request: {
                request_status: "Failed",
                grant_status: "ProvisionFailed",
              },
            },
          ],
        },
      }),
    };

    render(
      <AdminFailedTaskConsole
        apiClient={apiClient}
        authContext={{
          userId: "it_admin_001",
          operatorType: "ITAdmin",
          source: "dev_stub",
        }}
      />
    );

    await waitFor(() => {
      expect(apiClient.listFailedTasks).toHaveBeenCalled();
    });

    expect(screen.getAllByText("it_admin_001")).not.toHaveLength(0);
    expect(screen.getByText(/页面筛选不会覆盖真实身份边界/)).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "管理员 user_id" })).not.toBeInTheDocument();
    expect(apiClient.listFailedTasks).toHaveBeenLastCalledWith(
      expect.not.objectContaining({
        userId: expect.any(String),
      })
    );
    expect(await screen.findByText("ctk_failed_001")).toBeInTheDocument();
    expect(screen.getByText(/task_type：/)).toBeInTheDocument();
    expect(screen.getByText(/最近错误：Connector timeout/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "打开补偿页" })).toBeInTheDocument();
  });
});
