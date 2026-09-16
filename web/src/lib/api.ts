import type { UsageOverview } from "@/types/api";

const API_INTERNAL_URL = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

export async function getUsageOverview(): Promise<UsageOverview | null> {
  try {
    const res = await fetch(`${API_INTERNAL_URL}/api/stats/usage`, {
      cache: "no-store",
    });
    if (!res.ok) return null;
    return (await res.json()) as UsageOverview;
  } catch {
    return null;
  }
}
