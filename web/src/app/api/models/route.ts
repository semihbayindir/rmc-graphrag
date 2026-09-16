import { NextResponse } from "next/server";

// force-dynamic: build sırasında statik üretilmesin.
export const dynamic = "force-dynamic";

const API_INTERNAL_URL = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

export async function GET() {
  const res = await fetch(`${API_INTERNAL_URL}/api/models`, { cache: "no-store" });
  const data = await res.text();
  return new NextResponse(data, {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
}
