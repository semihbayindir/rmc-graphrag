import React from "react";
import type { DocRow } from "@/types/api";

export default function DocCard({ doc }: { doc: DocRow }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm dark:border-gray-800 dark:bg-white/[0.03]">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full bg-brand-50 px-2 py-0.5 text-xs font-medium text-brand-600 dark:bg-brand-500/15 dark:text-brand-400">
          API · {doc.protocol}
        </span>
        <span className="text-xs text-gray-500 dark:text-gray-400">
          {doc.service}
          {doc.method ? ` / ${doc.method}` : ""}
        </span>
        <a
          href={doc.url}
          target="_blank"
          rel="noopener noreferrer"
          className="ml-auto text-xs text-brand-500 hover:underline"
        >
          Confluence&apos;ta aç ↗
        </a>
      </div>
      {doc.summary && <p className="mt-2 text-gray-700 dark:text-gray-300">{doc.summary}</p>}
    </div>
  );
}
