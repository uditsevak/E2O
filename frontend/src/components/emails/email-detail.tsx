"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  ArrowLeftIcon,
  DownloadIcon,
  FileIcon,
  FileSpreadsheetIcon,
  FileTextIcon,
  ImageIcon,
  MailIcon,
} from "lucide-react";

import { ErrorState, PageSkeleton } from "@/components/app/states";
import { Avatar } from "@/components/app/user-menu";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { fileSize, fullDate } from "@/lib/format";
import { useMessage, type MessageDetail } from "@/lib/queries";
import { useWorkspace } from "@/lib/use-workspace";

type Address = MessageDetail["to_addresses"][number];

function formatAddresses(list: Address[]): string {
  return list.map((a) => (a.name ? `${a.name} <${a.address}>` : a.address)).join(", ");
}

function AttachmentIcon({ type }: { type: string }) {
  if (type.startsWith("image/")) return <ImageIcon className="text-primary size-5" />;
  if (type === "application/pdf") return <FileTextIcon className="text-destructive size-5" />;
  if (type.includes("sheet") || type.includes("excel") || type === "text/csv")
    return <FileSpreadsheetIcon className="text-success size-5" />;
  if (type === "message/rfc822") return <MailIcon className="text-muted-foreground size-5" />;
  return <FileIcon className="text-muted-foreground size-5" />;
}

export function EmailDetail() {
  const { wid } = useWorkspace();
  const { messageId } = useParams<{ messageId: string }>();
  const message = useMessage(wid, messageId);
  const [showHtml, setShowHtml] = useState(false);

  const back = (
    <Button variant="ghost" size="sm" className="mb-3 -ml-2" asChild>
      <Link href={`/w/${wid}/emails`}>
        <ArrowLeftIcon /> All emails
      </Link>
    </Button>
  );

  if (message.isPending) return <PageSkeleton />;
  if (message.error) {
    return (
      <>
        {back}
        <ErrorState error={message.error} onRetry={() => message.refetch()} />
      </>
    );
  }

  const m = message.data;
  const sender = m.from_name || m.from_address || "Unknown sender";
  const attachments = m.attachments.filter((a) => !a.is_inline);

  return (
    <article>
      {back}
      <h1 className="text-xl leading-snug font-semibold tracking-tight md:text-2xl">
        {m.subject || "(no subject)"}
      </h1>
      <div className="mt-2 flex flex-wrap gap-2">
        <Badge variant="outline">{m.source_name}</Badge>
        {m.direction === "outbound" && <Badge variant="secondary">Sent by your team</Badge>}
      </div>

      <div className="bg-card mt-5 rounded-xl border">
        <div className="flex items-start gap-3 border-b p-4">
          <Avatar name={sender} className="size-10" />
          <div className="min-w-0 flex-1 text-sm">
            <div className="flex flex-wrap items-baseline justify-between gap-x-3">
              <span className="font-semibold">{sender}</span>
              <span className="text-muted-foreground text-xs">{fullDate(m.sent_at)}</span>
            </div>
            {m.from_name && m.from_address && (
              <div className="text-muted-foreground truncate">{m.from_address}</div>
            )}
            {m.to_addresses.length > 0 && (
              <div className="text-muted-foreground mt-1">
                <span className="text-foreground font-medium">To:</span>{" "}
                {formatAddresses(m.to_addresses)}
              </div>
            )}
            {m.cc_addresses.length > 0 && (
              <div className="text-muted-foreground">
                <span className="text-foreground font-medium">Cc:</span>{" "}
                {formatAddresses(m.cc_addresses)}
              </div>
            )}
          </div>
        </div>

        {attachments.length > 0 && (
          <div className="grid gap-2 border-b p-4 sm:grid-cols-2">
            {attachments.map((a) => (
              <a
                key={a.id}
                href={`/api/w/${wid}/attachments/${a.id}/download`}
                className="hover:bg-accent flex items-center gap-3 rounded-lg border p-3 transition-colors"
              >
                <AttachmentIcon type={a.content_type} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">{a.filename}</span>
                  <span className="text-muted-foreground block text-xs">
                    {fileSize(a.size_bytes)}
                  </span>
                </span>
                <DownloadIcon className="text-muted-foreground size-4" />
              </a>
            ))}
          </div>
        )}

        <div className="p-4">
          {showHtml ? (
            <iframe
              title="Original email"
              sandbox=""
              src={`/api/w/${wid}/messages/${m.id}/html`}
              className="h-[70vh] w-full rounded-md border bg-white"
            />
          ) : (
            <div className="text-sm leading-relaxed break-words whitespace-pre-wrap">
              {m.body_text || (
                <span className="text-muted-foreground">(This email has no text)</span>
              )}
            </div>
          )}
          {m.has_html && (
            <Button
              variant="link"
              size="sm"
              className="mt-3 px-0"
              onClick={() => setShowHtml((v) => !v)}
            >
              {showHtml ? "Show plain text" : "Show original formatting"}
            </Button>
          )}
        </div>
      </div>
    </article>
  );
}
