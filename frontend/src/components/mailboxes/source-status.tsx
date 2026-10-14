import { Badge } from "@/components/ui/badge";
import type { Source } from "@/lib/queries";

export function SourceStatusBadge({ source }: { source: Source }) {
  if (source.status === "error") return <Badge variant="destructive">Needs attention</Badge>;
  if (source.status === "paused") return <Badge variant="secondary">Paused</Badge>;
  if (source.status === "disconnected") return <Badge variant="outline">Disconnected</Badge>;
  if (!source.backfill_completed_at) return <Badge variant="warning">Reading past emails…</Badge>;
  if (source.last_error) return <Badge variant="warning">Having trouble</Badge>;
  return <Badge variant="success">Connected</Badge>;
}
