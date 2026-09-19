import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Search as SearchIcon } from "lucide-react";
import { Fragment, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";

import { Card, PageHeader, Spinner } from "../components/ui";
import { api, qs } from "../lib/api";
import { prettyModel, relativeTime, shortRepo } from "../lib/format";
import type { Me, SearchHit } from "../lib/types";

const KINDS = [
  { value: "", label: "Everything" },
  { value: "text", label: "Conversation" },
  { value: "tool_use", label: "Commands and edits" },
  { value: "tool_result", label: "Tool output" },
];

const EXAMPLES = ["migration rollback", "flaky test", "rate limit", "\"connection refused\"", "feature flag"];

function Snippet({ text }: { text: string }) {
  const parts = text.split(/(<<.*?>>)/g);
  return (
    <>
      {parts.map((p, i) =>
        p.startsWith("<<") && p.endsWith(">>") ? (
          <mark key={i} className="rounded bg-accent-soft px-0.5 text-accent-ink">
            {p.slice(2, -2)}
          </mark>
        ) : (
          <Fragment key={i}>{p}</Fragment>
        ),
      )}
    </>
  );
}

export function SearchPage({ me }: { me: Me }) {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const kind = params.get("kind") ?? "";
  const [draft, setDraft] = useState(q);
  useEffect(() => setDraft(q), [q]);

  const results = useQuery({
    queryKey: ["search", q, kind],
    queryFn: () => api<{ items: SearchHit[]; total: number }>(`/api/search${qs({ q, kind: kind || undefined, limit: 50 })}`),
    enabled: q.trim().length >= 2,
    placeholderData: keepPreviousData,
  });

  const submit = (value: string) =>
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      if (value.trim()) next.set("q", value.trim());
      else next.delete("q");
      return next;
    });

  return (
    <div className="max-w-4xl">
      <PageHeader
        title="Search"
        sub={
          me.scope === "organisation"
            ? "Everything people and agents said and did, across every session in the organisation."
            : me.scope === "team"
              ? "Everything said and done in your teams' sessions."
              : "Everything said and done in your sessions."
        }
      />
      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit(draft);
        }}
        className="relative"
      >
        <SearchIcon className="pointer-events-none absolute top-1/2 left-4 size-5 -translate-y-1/2 text-muted" />
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          autoFocus
          placeholder="How did we fix the checkout race? Who touched the billing migration?"
          aria-label="Search sessions"
          className="h-12 w-full rounded-xl border border-line bg-surface pr-4 pl-12 text-[15px] shadow-card placeholder:text-muted focus:border-accent focus:ring-2 focus:ring-accent/20 focus:outline-none"
        />
      </form>
      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        {KINDS.map((k) => (
          <button
            key={k.value}
            onClick={() =>
              setParams((prev) => {
                const next = new URLSearchParams(prev);
                if (k.value) next.set("kind", k.value);
                else next.delete("kind");
                return next;
              })
            }
            className={
              "rounded-lg border px-2.5 py-1 text-[13px] " +
              (kind === k.value ? "border-accent/40 bg-accent-soft font-medium text-accent-ink" : "border-line bg-surface text-ink-2 hover:bg-surface-2")
            }
          >
            {k.label}
          </button>
        ))}
        {results.data && q && <span className="ml-auto text-sm text-muted">{results.data.total.toLocaleString()} matches</span>}
      </div>

      {!q ? (
        <Card className="mt-6 p-6">
          <p className="text-sm text-muted">
            Search works across prompts, agent replies, the commands agents ran, the files they edited and what those commands printed.
            Use quotes for exact phrases and <span className="font-mono">-word</span> to exclude.
          </p>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {EXAMPLES.map((e) => (
              <button key={e} onClick={() => submit(e)} className="rounded-md bg-surface-2 px-2 py-1 font-mono text-[12.5px] text-ink-2 hover:text-ink">
                {e}
              </button>
            ))}
          </div>
        </Card>
      ) : results.isLoading ? (
        <div className="mt-8">
          <Spinner />
        </div>
      ) : results.data && results.data.items.length ? (
        <ul className="mt-4 space-y-2">
          {results.data.items.map((hit) => (
            <li key={`${hit.session_id}-${hit.seq}-${hit.kind}`}>
              <Link to={`/sessions/${hit.session_id}#m-${hit.seq}`}>
                <Card className="p-4 transition-colors hover:border-line-strong">
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
                    <span className="font-medium text-ink">{hit.session.actor ? `${hit.session.actor} for ${hit.session.owner}` : hit.session.owner}</span>
                    <span>·</span>
                    <span className="font-mono">{shortRepo(hit.session.repo) || "no repo"}</span>
                    <span>·</span>
                    <span>{hit.kind === "text" ? (hit.role === "user" ? "prompt" : "reply") : hit.kind === "tool_use" ? hit.tool_name ?? "tool" : `${hit.tool_name ?? "tool"} output`}</span>
                    <span className="ml-auto">{relativeTime(hit.at)}</span>
                  </div>
                  <p className="mt-2 text-sm leading-relaxed text-ink-2">
                    <Snippet text={hit.snippet} />
                  </p>
                  <div className="mt-2 truncate text-xs text-muted">
                    {hit.session.title ?? "Untitled session"} · {prettyModel(hit.session.agent_model)}
                  </div>
                </Card>
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-8 text-center text-sm text-muted">Nothing matches. Try fewer or different words.</p>
      )}
    </div>
  );
}
