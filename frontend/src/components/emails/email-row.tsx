import Link from "next/link";
import { PaperclipIcon, ReplyIcon } from "lucide-react";

import { Avatar } from "@/components/app/user-menu";
import { Badge } from "@/components/ui/badge";
import { shortDate } from "@/lib/format";
import type { MessageItem } from "@/lib/queries";
import { cn } from "@/lib/utils";

export function EmailRow({
  wid,
  message,
  showSource,
}: {
  wid: string;
  message: MessageItem;
  showSource?: boolean;
}) {
  const sender = message.from_name || message.from_address || "Unknown sender";
  const outbound = message.direction === "outbound";
  return (
    <Link
      href={`/w/${wid}/emails/${message.id}`}
      className="hover:bg-accent/60 focus-visible:bg-accent flex items-start gap-3 px-4 py-3.5 transition-colors focus-visible:outline-none"
    >
      <Avatar
        name={sender}
        className={cn("mt-0.5 size-9", outbound && "bg-primary/10 text-primary")}
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="truncate text-sm font-semibold">{sender}</span>
          {outbound && (
            <Badge variant="secondary" className="gap-1">
              <ReplyIcon /> Sent
            </Badge>
          )}
          <span className="text-muted-foreground ml-auto shrink-0 text-xs tabular-nums">
            {shortDate(message.sent_at)}
          </span>
        </div>
        <div className="mt-0.5 flex items-center gap-1.5">
          <span className="truncate text-sm">{message.subject || "(no subject)"}</span>
          {message.attachment_count > 0 && (
            <PaperclipIcon
              className="text-muted-foreground size-3.5 shrink-0"
              aria-label={`${message.attachment_count} attachments`}
            />
          )}
        </div>
        <p className="text-muted-foreground mt-0.5 line-clamp-1 text-sm">
          {showSource && <span className="font-medium">{message.source_name} · </span>}
          {message.snippet}
        </p>
      </div>
    </Link>
  );
}
