"use client";

import { useDeferredValue, useState } from "react";
import Link from "next/link";
import { InboxIcon, Loader2Icon, SearchIcon } from "lucide-react";

import { EmptyState, ErrorState, ListSkeleton, PageHeader } from "@/components/app/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { plural } from "@/lib/format";
import { useMessages, useSources, type Direction } from "@/lib/queries";
import { useWorkspace } from "@/lib/use-workspace";
import { cn } from "@/lib/utils";

import { EmailRow } from "./email-row";

const TABS: { value: Direction | undefined; label: string }[] = [
  { value: undefined, label: "All" },
  { value: "inbound", label: "Received" },
  { value: "outbound", label: "Sent" },
];

export function EmailList() {
  const { wid } = useWorkspace();
  const [direction, setDirection] = useState<Direction | undefined>();
  const [sourceId, setSourceId] = useState<string>("");
  const [search, setSearch] = useState("");
  const q = useDeferredValue(search.trim());
  const sources = useSources(wid);
  const messages = useMessages(wid, {
    direction,
    source_id: sourceId || undefined,
    q: q || undefined,
  });

  const items = messages.data?.pages.flatMap((p) => p.items) ?? [];
  const total = messages.data?.pages[0]?.total ?? 0;
  const multipleSources = (sources.data?.length ?? 0) > 1;
  const noSources = sources.data?.length === 0;

  return (
    <>
      <PageHeader
        title="Emails"
        description={
          messages.data ? `${plural(total, "email")} from your connected mailboxes` : undefined
        }
      />

      <div className="mb-4 space-y-3">
        <div className="relative">
          <SearchIcon className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2" />
          <Input
            type="search"
            placeholder="Search by sender, subject or text"
            className="pl-9"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="bg-card inline-flex rounded-lg border p-0.5" role="tablist">
            {TABS.map((tab) => (
              <button
                key={tab.label}
                role="tab"
                aria-selected={direction === tab.value}
                onClick={() => setDirection(tab.value)}
                className={cn(
                  "text-muted-foreground rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                  direction === tab.value && "bg-primary text-primary-foreground shadow-xs",
                )}
              >
                {tab.label}
              </button>
            ))}
          </div>
          {multipleSources && (
            <div className="min-w-44 flex-1 sm:max-w-60 sm:flex-none">
              <NativeSelect
                aria-label="Mailbox"
                value={sourceId}
                onChange={(e) => setSourceId(e.target.value)}
              >
                <option value="">All mailboxes</option>
                {sources.data?.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.display_name}
                  </option>
                ))}
              </NativeSelect>
            </div>
          )}
        </div>
      </div>

      {messages.isPending ? (
        <ListSkeleton />
      ) : messages.error ? (
        <ErrorState error={messages.error} onRetry={() => messages.refetch()} />
      ) : items.length === 0 ? (
        noSources ? (
          <EmptyState icon={<InboxIcon />} title="No mailboxes connected yet">
            Connect your company or sales mailbox and emails will show up here within minutes.
            <div className="mt-4">
              <Button asChild>
                <Link href={`/w/${wid}/mailboxes/connect`}>Connect a mailbox</Link>
              </Button>
            </div>
          </EmptyState>
        ) : (
          <EmptyState
            icon={<InboxIcon />}
            title={q ? "No emails match your search" : "No emails yet"}
          >
            {q
              ? "Try a different name, company or word."
              : "We check your mailboxes every few minutes. New emails will appear here."}
          </EmptyState>
        )
      ) : (
        <>
          <div
            className={cn(
              "bg-card divide-y overflow-hidden rounded-xl border transition-opacity",
              messages.isPlaceholderData && "opacity-60",
            )}
          >
            {items.map((m) => (
              <EmailRow
                key={m.id}
                wid={wid}
                message={m}
                showSource={multipleSources && !sourceId}
              />
            ))}
          </div>
          {messages.hasNextPage && (
            <div className="mt-4 flex justify-center">
              <Button
                variant="outline"
                onClick={() => messages.fetchNextPage()}
                disabled={messages.isFetchingNextPage}
              >
                {messages.isFetchingNextPage && <Loader2Icon className="animate-spin" />} Show more
              </Button>
            </div>
          )}
        </>
      )}
    </>
  );
}
