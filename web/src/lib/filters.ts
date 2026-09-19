import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router";

/** Filters live in the URL, so any view of the R&D screen is a shareable link. */

export const RANGES = [
  { value: "24h", label: "24 hours", hours: 24 },
  { value: "7d", label: "7 days", hours: 24 * 7 },
  { value: "30d", label: "30 days", hours: 24 * 30 },
  { value: "90d", label: "90 days", hours: 24 * 90 },
  { value: "all", label: "All time", hours: null },
] as const;

export type RangeValue = (typeof RANGES)[number]["value"];

export const LIST_KEYS = ["owner", "team", "repo", "vendor", "model", "status", "outcome", "worker"] as const;
export type ListKey = (typeof LIST_KEYS)[number];

export interface FilterState {
  range: RangeValue;
  q: string;
  task_ref: string;
  lists: Record<ListKey, string[]>;
}

export function useFilters() {
  const [params, setParams] = useSearchParams();

  const state: FilterState = useMemo(() => {
    const range = (RANGES.find((r) => r.value === params.get("range"))?.value ?? "7d") as RangeValue;
    const lists = Object.fromEntries(LIST_KEYS.map((k) => [k, params.getAll(k)])) as Record<ListKey, string[]>;
    return { range, q: params.get("q") ?? "", task_ref: params.get("task_ref") ?? "", lists };
  }, [params]);

  const update = useCallback(
    (fn: (p: URLSearchParams) => void) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          fn(next);
          next.delete("page");
          return next;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  const setList = useCallback(
    (key: ListKey, values: string[]) =>
      update((p) => {
        p.delete(key);
        values.forEach((v) => p.append(key, v));
      }),
    [update],
  );

  const setRange = useCallback((r: RangeValue) => update((p) => (r === "7d" ? p.delete("range") : p.set("range", r))), [update]);
  const setQuery = useCallback((q: string) => update((p) => (q ? p.set("q", q) : p.delete("q"))), [update]);
  const setTaskRef = useCallback((t: string) => update((p) => (t ? p.set("task_ref", t) : p.delete("task_ref"))), [update]);
  const clearAll = useCallback(
    () =>
      update((p) => {
        [...LIST_KEYS, "q", "task_ref"].forEach((k) => p.delete(k));
      }),
    [update],
  );

  const active = LIST_KEYS.some((k) => state.lists[k].length > 0) || !!state.q || !!state.task_ref;

  /** Query parameters for the API. `since` is rounded to the minute so the query key stays stable. */
  const apiParams = useMemo(() => {
    const hours = RANGES.find((r) => r.value === state.range)?.hours;
    const since = hours ? new Date(Math.floor((Date.now() - hours * 3600_000) / 60_000) * 60_000).toISOString() : undefined;
    const { worker, ...lists } = state.lists;
    const actor_kind = worker.length === 1 ? worker[0] : undefined;
    return { ...lists, actor_kind, q: state.q || undefined, task_ref: state.task_ref || undefined, since };
  }, [state, Math.floor(Date.now() / 60_000)]);

  const page = Math.max(0, Number(params.get("page") ?? 0) || 0);
  const setPage = useCallback(
    (n: number) =>
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (n) next.set("page", String(n));
          else next.delete("page");
          return next;
        },
        { replace: true },
      ),
    [setParams],
  );

  const selected = params.get("session");
  const select = useCallback(
    (id: string | null) =>
      setParams((prev) => {
        const next = new URLSearchParams(prev);
        if (id) next.set("session", id);
        else next.delete("session");
        return next;
      }),
    [setParams],
  );

  return { state, apiParams, active, setList, setRange, setQuery, setTaskRef, clearAll, page, setPage, selected, select };
}
