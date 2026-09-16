import React from "react";
import Badge from "@/components/ui/badge/Badge";
import type { EvidenceRow } from "@/types/api";
import { OUTCOME_BADGE_COLOR, OUTCOME_LABEL } from "./outcome";

export default function EvidenceCard({ row }: { row: EvidenceRow }) {
  const color = (row.outcome && OUTCOME_BADGE_COLOR[row.outcome]) || "light";
  const label = (row.outcome && OUTCOME_LABEL[row.outcome]) || row.outcome || "—";

  return (
    <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm dark:border-gray-800 dark:bg-white/[0.03]">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-gray-500 dark:text-gray-400">
          #{row.ticket_id}
        </span>
        <Badge size="sm" color={color}>
          {label}
        </Badge>
        {row.modul && (
          <span className="text-xs text-gray-500 dark:text-gray-400">
            {row.modul}
            {row.feature ? ` / ${row.feature}` : ""}
          </span>
        )}
        {row.ekipler.length > 0 && (
          <span className="text-xs text-gray-400 dark:text-gray-500">
            ekip: {row.ekipler.join(", ")}
          </span>
        )}
      </div>
      {row.symptom && (
        <p className="mt-2 text-gray-700 dark:text-gray-300">{row.symptom}</p>
      )}
    </div>
  );
}
