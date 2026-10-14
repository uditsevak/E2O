"use client";

import { useState } from "react";
import Link from "next/link";
import {
  AlertTriangleIcon,
  Loader2Icon,
  MailIcon,
  MoreVerticalIcon,
  PauseIcon,
  PlayIcon,
  PlusIcon,
  RefreshCwIcon,
  UnplugIcon,
} from "lucide-react";
import { toast } from "sonner";

import { EmptyState, ErrorState, ListSkeleton, PageHeader } from "@/components/app/states";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { errorMessage } from "@/lib/api/client";
import { plural, timeAgo } from "@/lib/format";
import {
  useDisconnectSource,
  useSources,
  useSyncSource,
  useUpdateSource,
  type Source,
} from "@/lib/queries";
import { useWorkspace } from "@/lib/use-workspace";

import { SourceStatusBadge } from "./source-status";
import { TrustPanel } from "./trust-panel";
import { useFieldId } from "@/lib/use-field-id";

function PasswordDialog({
  wid,
  source,
  open,
  onOpenChange,
}: {
  wid: string;
  source: Source;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const fid = useFieldId();
  const update = useUpdateSource(wid);
  const [password, setPassword] = useState("");
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Update password</DialogTitle>
          <DialogDescription>
            Enter the current password (or app password) for {source.account_address}.
          </DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            update.mutate(
              { id: source.id, body: { password } },
              {
                onSuccess: () => {
                  toast.success("Mailbox reconnected");
                  setPassword("");
                  onOpenChange(false);
                },
              },
            );
          }}
        >
          {update.error && (
            <Alert variant="destructive">
              <AlertDescription>{errorMessage(update.error)}</AlertDescription>
            </Alert>
          )}
          <div className="space-y-2">
            <Label htmlFor={fid("new-password")}>Password</Label>
            <Input
              id={fid("new-password")}
              type="password"
              autoComplete="off"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          <DialogFooter>
            <Button type="submit" disabled={update.isPending}>
              {update.isPending && <Loader2Icon className="animate-spin" />} Test and save
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function DisconnectDialog({
  wid,
  source,
  open,
  onOpenChange,
}: {
  wid: string;
  source: Source;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const disconnect = useDisconnectSource(wid);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Disconnect {source.display_name}?</DialogTitle>
          <DialogDescription>
            We&apos;ll stop reading this mailbox and delete the stored password. Emails already
            brought in stay here.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            disabled={disconnect.isPending}
            onClick={() =>
              disconnect.mutate(source.id, {
                onSuccess: () => {
                  toast.success("Mailbox disconnected");
                  onOpenChange(false);
                },
                onError: (e) => toast.error(errorMessage(e)),
              })
            }
          >
            Disconnect
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function MailboxCard({ wid, source, isAdmin }: { wid: string; source: Source; isAdmin: boolean }) {
  const sync = useSyncSource(wid);
  const update = useUpdateSource(wid);
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [disconnectOpen, setDisconnectOpen] = useState(false);
  const settings = source.settings as { host?: string; outbound_folder?: string | null };

  return (
    <div className="bg-card rounded-xl border p-4">
      <div className="flex items-start gap-3">
        <span className="bg-accent text-primary flex size-10 shrink-0 items-center justify-center rounded-full">
          <MailIcon className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate font-semibold">{source.display_name}</span>
            <SourceStatusBadge source={source} />
          </div>
          <div className="text-muted-foreground truncate text-sm">{source.account_address}</div>
          <div className="text-muted-foreground mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
            <span>{plural(source.message_count, "email")}</span>
            {source.status !== "disconnected" && (
              <span>Checked {timeAgo(source.last_synced_at)}</span>
            )}
            {settings.host && <span>{settings.host}</span>}
            {source.status !== "disconnected" && !settings.outbound_folder && (
              <span className="text-warning">No Sent folder found</span>
            )}
          </div>
        </div>
        {isAdmin && source.status !== "disconnected" && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" aria-label="Mailbox options">
                <MoreVerticalIcon />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {source.status === "active" && (
                <DropdownMenuItem
                  onSelect={() =>
                    sync.mutate(source.id, {
                      onSuccess: () => toast.success("Checking for new emails"),
                      onError: (e) => toast.error(errorMessage(e)),
                    })
                  }
                >
                  <RefreshCwIcon /> Check now
                </DropdownMenuItem>
              )}
              <DropdownMenuItem onSelect={() => setPasswordOpen(true)}>
                <AlertTriangleIcon /> Update password
              </DropdownMenuItem>
              {(source.status === "active" || source.status === "paused") && (
                <DropdownMenuItem
                  onSelect={() =>
                    update.mutate({ id: source.id, body: { paused: source.status === "active" } })
                  }
                >
                  {source.status === "active" ? <PauseIcon /> : <PlayIcon />}
                  {source.status === "active" ? "Pause" : "Resume"}
                </DropdownMenuItem>
              )}
              <DropdownMenuSeparator />
              <DropdownMenuItem variant="destructive" onSelect={() => setDisconnectOpen(true)}>
                <UnplugIcon /> Disconnect
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>

      {source.last_error && source.status !== "disconnected" && (
        <Alert variant={source.status === "error" ? "destructive" : "warning"} className="mt-3">
          <AlertTriangleIcon />
          <AlertDescription>
            <p>{source.last_error}</p>
            {isAdmin && source.status === "error" && (
              <Button size="sm" className="mt-2" onClick={() => setPasswordOpen(true)}>
                Update password
              </Button>
            )}
          </AlertDescription>
        </Alert>
      )}

      <PasswordDialog
        wid={wid}
        source={source}
        open={passwordOpen}
        onOpenChange={setPasswordOpen}
      />
      <DisconnectDialog
        wid={wid}
        source={source}
        open={disconnectOpen}
        onOpenChange={setDisconnectOpen}
      />
    </div>
  );
}

export function MailboxList() {
  const { wid, isAdmin } = useWorkspace();
  const sources = useSources(wid);

  const connectButton = isAdmin && (
    <Button asChild>
      <Link href={`/w/${wid}/mailboxes/connect`}>
        <PlusIcon /> Connect a mailbox
      </Link>
    </Button>
  );

  return (
    <>
      <PageHeader
        title="Mailboxes"
        description="The inboxes we read enquiries from."
        actions={sources.data?.length ? connectButton : undefined}
      />
      {sources.isPending ? (
        <ListSkeleton rows={2} />
      ) : sources.error ? (
        <ErrorState error={sources.error} onRetry={() => sources.refetch()} />
      ) : sources.data.length === 0 ? (
        <div className="grid gap-4 md:grid-cols-[1fr_20rem]">
          <EmptyState icon={<MailIcon />} title="No mailboxes yet">
            Connect the company inbox, and each salesperson&apos;s mailbox, so no enquiry is missed.
            <div className="mt-4">
              {connectButton || "Ask your workspace owner to connect one."}
            </div>
          </EmptyState>
          <TrustPanel />
        </div>
      ) : (
        <div className="space-y-3">
          {sources.data.map((s) => (
            <MailboxCard key={s.id} wid={wid} source={s} isAdmin={isAdmin} />
          ))}
        </div>
      )}
    </>
  );
}
