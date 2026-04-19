import { describe, expect, it, vi } from "vitest";

import { listAuditRecords } from "../../../../lib/admin-api";
import { GET } from "./route";

vi.mock("../../../../lib/admin-api", () => ({
  listAuditRecords: vi.fn(),
}));

describe("GET /api/admin/audit-records", () => {
  it("ignores forged browser identity parameters and delegates filters only", async () => {
    listAuditRecords.mockResolvedValue({
      status: 200,
      payload: { data: { items: [], total: 0 } },
    });

    const response = await GET({
      nextUrl: new URL(
        "http://localhost/api/admin/audit-records?userId=evil_admin&operatorType=ITAdmin&requestId=req_001"
      ),
    });
    const payload = await response.json();

    expect(response.status).toBe(200);
    expect(payload).toEqual({ data: { items: [], total: 0 } });
    expect(listAuditRecords).toHaveBeenCalledWith(
      expect.objectContaining({
        requestId: "req_001",
      })
    );
    expect(listAuditRecords).toHaveBeenCalledWith(
      expect.not.objectContaining({
        userId: expect.any(String),
        operatorType: expect.any(String),
      })
    );
  });
});
