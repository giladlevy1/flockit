import { Fragment, type ReactNode } from "react";

/**
 * A deliberately small Markdown renderer for agent output: headings, paragraphs,
 * lists, fenced code, inline code, bold, italics and http(s) links. It builds React
 * elements, never HTML strings, so transcript content cannot inject markup.
 */
export function Markdown({ text, className }: { text: string; className?: string }) {
  return <div className={"space-y-2 text-sm leading-relaxed break-words " + (className ?? "")}>{blocks(text)}</div>;
}

function inline(text: string, key = 0): ReactNode[] {
  const out: ReactNode[] = [];
  const pattern = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\[[^\]]+\]\(https?:\/\/[^\s)]+\))|(https?:\/\/[^\s)<>"']+)|(\*[^*\s][^*]*\*)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = pattern.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const token = m[0];
    const k = `${key}-${i++}`;
    if (m[1]) out.push(<code key={k} className="rounded bg-surface-2 px-1 py-0.5 font-mono text-[0.9em]">{token.slice(1, -1)}</code>);
    else if (m[2]) out.push(<strong key={k} className="font-semibold text-ink">{token.slice(2, -2)}</strong>);
    else if (m[3]) {
      const label = token.slice(1, token.indexOf("]"));
      const href = token.slice(token.indexOf("(") + 1, -1);
      out.push(<a key={k} href={href} target="_blank" rel="noreferrer noopener" className="text-accent-ink underline underline-offset-2">{label}</a>);
    } else if (m[4]) out.push(<a key={k} href={token} target="_blank" rel="noreferrer noopener" className="break-all text-accent-ink underline underline-offset-2">{token}</a>);
    else if (m[5]) out.push(<em key={k}>{token.slice(1, -1)}</em>);
    last = m.index + token.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function blocks(text: string): ReactNode[] {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const out: ReactNode[] = [];
  let i = 0;
  let key = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.trim().startsWith("```")) {
      const body: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) body.push(lines[i++]);
      i++;
      out.push(
        <pre key={key++} className="overflow-x-auto rounded-lg bg-surface-2 px-3 py-2 font-mono text-[12.5px] leading-relaxed">
          <code>{body.join("\n")}</code>
        </pre>,
      );
      continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      const size = heading[1].length <= 2 ? "text-[15px]" : "text-sm";
      out.push(<p key={key++} className={`${size} font-semibold text-ink`}>{inline(heading[2], key)}</p>);
      i++;
      continue;
    }
    if (/^\s*([-*•]|\d+[.)])\s+/.test(line)) {
      const ordered = /^\s*\d+[.)]/.test(line);
      const start = ordered ? Number(line.match(/\d+/)?.[0] ?? 1) : undefined;
      const items: string[] = [];
      const itemPattern = ordered ? /^\s*\d+[.)]\s+/ : /^\s*[-*•]\s+/;
      while (i < lines.length) {
        if (itemPattern.test(lines[i])) {
          items.push(lines[i].replace(itemPattern, ""));
          i++;
        } else if (!lines[i].trim() && i + 1 < lines.length && itemPattern.test(lines[i + 1])) {
          i++; // a blank line between items does not end the list
        } else if (/^\s{2,}\S/.test(lines[i]) && items.length) {
          items[items.length - 1] += " " + lines[i].trim(); // an indented continuation line
          i++;
        } else break;
      }
      const List = ordered ? "ol" : "ul";
      out.push(
        <List key={key++} start={start} className={(ordered ? "list-decimal" : "list-disc") + " space-y-1 pl-5 marker:text-muted"}>
          {items.map((item, n) => (
            <li key={n}>{inline(item, n)}</li>
          ))}
        </List>,
      );
      continue;
    }
    if (!line.trim()) {
      i++;
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|\s*([-*•]|\d+[.)])\s+)/.test(lines[i])) para.push(lines[i++]);
    out.push(
      <p key={key++}>
        {para.map((p, n) => (
          <Fragment key={n}>
            {n > 0 && <br />}
            {inline(p, n)}
          </Fragment>
        ))}
      </p>,
    );
  }
  return out;
}
