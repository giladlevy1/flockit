import { Badge } from "../ui";
import type { Session } from "../../lib/types";

export function StatusBadge({ s }: { s: Pick<Session, "status" | "outcome"> }) {
  if (s.status === "live")
    return (
      <Badge tone="live">
        <span className="live-dot mr-0.5 !size-1.5" /> Live
      </Badge>
    );
  if (s.status === "idle") return <Badge tone="warn">Idle</Badge>;
  switch (s.outcome) {
    case "completed":
      return <Badge>Completed</Badge>;
    case "abandoned":
      return <Badge tone="warn">Abandoned</Badge>;
    case "errored":
      return <Badge tone="bad">Errored</Badge>;
    default:
      return <Badge>Ended</Badge>;
  }
}

export function OriginBadge({ origin }: { origin: Session["origin"] }) {
  return origin === "workflow" ? <Badge tone="accent">Workflow</Badge> : null;
}

export const MODEL_COLORS = ["#e8622c", "#1f8a70", "#5b6ee1", "#c79a3c", "#8a94a6", "#b04fa0", "#2f9bd1"];
