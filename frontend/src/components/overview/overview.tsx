"use client";

import Link from "next/link";
import {
  AlertTriangleIcon,
  ArrowRightIcon,
  InboxIcon,
  MailPlusIcon,
  RefreshCwIcon,
} from "lucide-react";

import { EmptyState, ErrorState, PageSkeleton } from "@/components/app/states";
import { EmailRow } from "@/components/emails/email-row";
import { TrustPanel } from "@/components/mailboxes/trust-panel";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { greeting, plural, timeAgo } from "@/lib/format";
import { useMessages, useOverview, useSources } from "@/lib/queries";
import { useWorkspace } from "@/lib/use-workspace";

function Stat({ label, value, hint }: { label: string; value: number; hint?: string }) {
  return (
    <div className="bg-card rounded-xl border p-4">
      <div className="text-muted-foreground text-sm">{label}</div>
      <div className="mt-1 text-3xl font-semibold tabular-nums">
        {value.toLocaleString("en-IN")}
      </div>
      {hint && <div className="text-muted-foreground mt-1 text-xs">{hint}</div>}
    </div>
  );
}

export function Overview() {
  const { wid, me, workspace, isAdmin } = useWorkspace();
  const overview = useOverview(wid);
  const sources = useSources(wid);
  const recent = useMessages(wid, { direction: "inbound" });

  if (overview.isPending || sources.isPending) return <PageSkeleton />;
  if (overview.error)
    return <ErrorState error={overview.error} onRetry={() => overview.refetch()} />;

  const o = overview.data;
  const firstName = me?.user.name.split(" ")[0] ?? "";
  const needsAttention = sources.data?.filter((s) => s.status === "error") ?? [];
  const reading = sources.data?.some((s) => s.status === "active" && !s.backfill_completed_at);
  const latest = recent.data?.pages[0]?.items.slice(0, 5) ?? [];

  return (
    <>
      <div className="mb-5">
        <h1 className="text-xl font-semibold tracking-tight md:text-2xl">
          {greeting()}, {firstName}
        </h1>
        <p className="text-muted-foreground mt-1 text-sm">{workspace?.name}</p>
      </div>

      {o.sources_connected === 0 ? (
        <div className="grid gap-4 md:grid-cols-[1fr_20rem]">
          <EmptyState icon={<MailPlusIcon />} title="Connect your first mailbox">
            Add the company inbox or a salesperson&apos;s mailbox. We&apos;ll bring in the last 30
            days of emails and keep checking for new ones.
            <div className="mt-4">
              {isAdmin ? (
                <Button asChild>
                  <Link href={`/w/${wid}/mailboxes/connect`}>Connect a mailbox</Link>
                </Button>
              ) : (
                <span>Ask your workspace owner to connect a mailbox.</span>
              )}
            </div>
          </EmptyState>
          <TrustPanel />
        </div>
      ) : (
        <div className="space-y-5">
          {needsAttention.length > 0 && (
            <Alert variant="destructive">
              <AlertTriangleIcon />
              <AlertTitle>
                {needsAttention.length === 1
                  ? `${needsAttention[0].display_name} needs attention`
                  : `${needsAttention.length} mailboxes need attention`}
              </AlertTitle>
              <AlertDescription>
                <p>We can&apos;t read new emails until this is fixed.</p>
                <Link href={`/w/${wid}/mailboxes`} className="font-medium underline">
                  Fix it
                </Link>
              </AlertDescription>
            </Alert>
          )}

          <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
            <Stat label="Emails today" value={o.messages_today} />
            <Stat label="This week" value={o.messages_this_week} />
            <div className="bg-card col-span-2 rounded-xl border p-4 md:col-span-1">
              <div className="text-muted-foreground text-sm">Mailboxes</div>
              <div className="mt-1 text-3xl font-semibold tabular-nums">{o.sources_connected}</div>
              <div className="text-muted-foreground mt-1 flex items-center gap-1 text-xs">
                <RefreshCwIcon className={reading ? "size-3 animate-spin" : "size-3"} />
                {reading ? "Reading past emails…" : `Last checked ${timeAgo(o.last_synced_at)}`}
              </div>
            </div>
          </div>

          <Card className="gap-0 pb-0">
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center justify-between">
                <span>Latest emails</span>
                <Button variant="ghost" size="sm" asChild>
                  <Link href={`/w/${wid}/emails`}>
                    See all <ArrowRightIcon />
                  </Link>
                </Button>
              </CardTitle>
            </CardHeader>
            <CardContent className="px-0">
              {latest.length === 0 ? (
                <div className="text-muted-foreground flex items-center gap-2 border-t px-5 py-6 text-sm">
                  <InboxIcon className="size-4" />
                  {reading ? "Bringing in your emails…" : "No emails received yet."}
                </div>
              ) : (
                <div className="divide-y border-t">
                  {latest.map((m) => (
                    <EmailRow
                      key={m.id}
                      wid={wid}
                      message={m}
                      showSource={o.sources_connected > 1}
                    />
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
          <p className="text-muted-foreground text-xs">
            {plural(o.messages_this_week, "email")} received this week across{" "}
            {plural(o.sources_connected, "mailbox", "mailboxes")}.
          </p>
        </div>
      )}
    </>
  );
}
