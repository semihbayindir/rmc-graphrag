import type { Metadata } from "next";
import React from "react";
import UsageSection from "@/components/dashboard/UsageSection";
import { getUsageOverview } from "@/lib/api";

export const metadata: Metadata = {
  title: "İstatistikler",
  description: "RMC Bilgi Asistanı kullanım istatistikleri",
};

export default async function StatsPage() {
  const usage = await getUsageOverview();

  if (!usage) {
    return (
      <div className="rounded-2xl border border-gray-200 bg-white p-6 text-center dark:border-gray-800 dark:bg-white/[0.03]">
        <p className="text-gray-500 dark:text-gray-400">
          Veriler yüklenemedi — API'ye (
          <code>{process.env.API_INTERNAL_URL ?? "http://localhost:8000"}</code>)
          ulaşılamıyor.
        </p>
      </div>
    );
  }

  return <UsageSection data={usage} />;
}
