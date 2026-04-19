import { NextResponse } from "next/server";

import { listAuditRecords } from "../../../../lib/admin-api";

export async function GET(request) {
  const searchParams = request.nextUrl.searchParams;

  try {
    const result = await listAuditRecords({
      requestId: searchParams.get("requestId") ?? undefined,
      eventType: searchParams.get("eventType") ?? undefined,
      actorType: searchParams.get("actorType") ?? undefined,
      actorId: searchParams.get("actorId") ?? undefined,
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
