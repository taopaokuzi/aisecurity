import { NextResponse } from "next/server";

import { listAuditRecords } from "../../../../lib/admin-api";

function missingField(field) {
  return NextResponse.json(
    {
      error: {
        code: "BAD_REQUEST",
        message: `${field} is required`,
      },
    },
    { status: 400 }
  );
}

export async function GET(request) {
  const searchParams = request.nextUrl.searchParams;
  const userId = searchParams.get("userId");
  const operatorType = searchParams.get("operatorType");

  if (!userId) {
    return missingField("userId");
  }
  if (!operatorType) {
    return missingField("operatorType");
  }

  try {
    const result = await listAuditRecords({
      userId,
      operatorType,
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
