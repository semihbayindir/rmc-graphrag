import React from "react";

// Sadece kod bloğu, **kalın**, `kod` ve satır sonu.
export function formatText(text: string): React.ReactNode[] {
  // Tek indisler kod bloğu: "```json\n ... ```" açılış/kapanış çitleri ayırıcıdır.
  const chunks = text.split(/```[A-Za-z]*\n?/);
  return chunks.map((chunk, c) =>
    c % 2 === 1 ? (
      <pre
        key={c}
        className="my-2 overflow-x-auto whitespace-pre rounded-md bg-black/5 p-3 font-mono text-xs dark:bg-white/10"
      >
        <code>{chunk.replace(/\n$/, "")}</code>
      </pre>
    ) : (
      <React.Fragment key={c}>{formatLines(chunk)}</React.Fragment>
    )
  );
}

function formatLines(text: string): React.ReactNode[] {
  const lines = text.split("\n");
  return lines.map((line, i) => (
    <React.Fragment key={i}>
      {formatLine(line)}
      {i < lines.length - 1 && <br />}
    </React.Fragment>
  ));
}

function formatLine(line: string): React.ReactNode[] {
  const parts = line.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).filter(Boolean);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return (
        <code
          key={i}
          className="rounded bg-black/10 px-1 py-0.5 font-mono text-[0.85em] dark:bg-white/10"
        >
          {part.slice(1, -1)}
        </code>
      );
    }
    return <React.Fragment key={i}>{part}</React.Fragment>;
  });
}
