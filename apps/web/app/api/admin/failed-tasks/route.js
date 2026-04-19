import { NextResponse } from "next/server";

import { listFailedTasks } from "../../../../lib/admin-api";

export async function GET(request) {
  const searchParams = request.nextUrl.searchParams;

  try {
    const result = await listFailedTasks({
      taskType: searchParams.get("taskType") ?? undefined,
      taskStatus: searchParams.get("taskStatus") ?? undefined,
      requestId: searchParams.get("requestId") ?? undefined,
      grantId: searchParams.get("grantId") ?? undefined,
      page: Number(searchParams.get("page") ?? "1"),
      pageSize: Number(searchParams.get("pageSize") ?? "20"),
    });
    return NextResponse.json(result.payload, { status: result.status });
  } catch (error) {
    return NextResponse.json(
      {
        error: {
          code: "UPSTREAM_UNAVAILABLE",
          message: error instanceof Error ? error.message : "Backend request failed",
        },
      },
      { status: 502 }
    );
  }
}
