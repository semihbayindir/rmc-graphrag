import React from "react";
import { BoltIcon, ChatIcon, GroupIcon, TimeIcon } from "@/icons";
import StatCard from "@/components/dashboard/StatCard";
import type { UsageOverview } from "@/types/api";

const fmt = (n: number) => n.toLocaleString("tr-TR");
const secs = (ms: number | null) => (ms == null ? "—" : `${(ms / 1000).toFixed(1)} sn`);

// Soru bazındaki kayıtlar data/usage.db'den sorgulanır.
export default function UsageSection({ data }: { data: UsageOverview }) {
  if (data.total_questions === 0) {
    return (
      <div className="rounded-2xl border border-gray-200 bg-white p-6 text-center dark:border-gray-800 dark:bg-white/[0.03]">
        <p className="text-gray-500 dark:text-gray-400">
          Henüz kaydedilmiş bir soru yok — sohbet sayfası kullanılmaya başlandığında burada
          kullanım metrikleri görünecek.
        </p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4 md:gap-6">
      <h2 className="font-semibold text-gray-800 dark:text-white/90">Kullanım</h2>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4 md:gap-6">
        <StatCard
          icon={<ChatIcon className="text-gray-800 size-6 dark:text-white/90" />}
          label="Toplam Soru"
          value={fmt(data.total_questions)}
          sub={`${fmt(data.questions_last_7d)} son 7 günde`}
        />
        <StatCard
          icon={<GroupIcon className="text-gray-800 size-6 dark:text-white/90" />}
          label="Tekil Kullanıcı (anonim)"
          value={fmt(data.distinct_sessions)}
        />
        <StatCard
          icon={<TimeIcon className="text-gray-800 size-6 dark:text-white/90" />}
          label="Ortalama Yanıt Süresi"
          value={secs(data.avg_latency_ms)}
        />
        <StatCard
          icon={<BoltIcon className="text-gray-800 size-6 dark:text-white/90" />}
          label="Toplam Token"
          value={fmt(data.total_tokens)}
          sub={`${fmt(data.total_prompt_tokens)} girdi · ${fmt(data.total_output_tokens)} çıktı`}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2 md:gap-6">
        <div className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-white/[0.03] md:p-6">
          <h3 className="mb-4 font-semibold text-gray-800 dark:text-white/90">
            En Çok Sorulan Modüller
          </h3>
          {data.top_modules.length === 0 ? (
            <p className="text-sm text-gray-400">Henüz modül eşleşmesi yok.</p>
          ) : (
            <div className="space-y-3">
              {data.top_modules.map((m) => {
                const max = data.top_modules[0].c;
                return (
                  <div key={m.module}>
                    <div className="mb-1 flex justify-between text-sm">
                      <span className="text-gray-700 dark:text-gray-300">{m.module}</span>
                      <span className="text-gray-400">{m.c}</span>
                    </div>
                    <div className="h-2 rounded-full bg-gray-100 dark:bg-white/10">
                      <div
                        className="h-2 rounded-full bg-brand-500"
                        style={{ width: `${(m.c / max) * 100}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <div className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-white/[0.03] md:p-6">
          <h3 className="mb-4 font-semibold text-gray-800 dark:text-white/90">
            Geri Bildirim
          </h3>
          <div className="flex gap-6">
            <div>
              <p className="text-2xl font-bold text-success-600">{data.feedback.up}</p>
              <p className="text-sm text-gray-500 dark:text-gray-400">👍 Beğenildi</p>
            </div>
            <div>
              <p className="text-2xl font-bold text-error-600">{data.feedback.down}</p>
              <p className="text-sm text-gray-500 dark:text-gray-400">👎 Beğenilmedi</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
