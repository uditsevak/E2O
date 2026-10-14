"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { CopyIcon, Loader2Icon, MessageCircleIcon, UserPlusIcon, XIcon } from "lucide-react";
import { toast } from "sonner";

import { ErrorState, ListSkeleton, PageHeader } from "@/components/app/states";
import { Avatar } from "@/components/app/user-menu";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { errorMessage } from "@/lib/api/client";
import { shortDate } from "@/lib/format";
import {
  useCreateInvite,
  useInvites,
  useMembers,
  useRemoveMember,
  useRevokeInvite,
} from "@/lib/queries";
import { useWorkspace } from "@/lib/use-workspace";
import { useFieldId } from "@/lib/use-field-id";

const ROLE_LABEL = { owner: "Owner", admin: "Admin", member: "Member" } as const;

function InviteForm({ wid, canInviteOwner }: { wid: string; canInviteOwner: boolean }) {
  const fid = useFieldId();
  const create = useCreateInvite(wid);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<"member" | "admin" | "owner">("member");
  const [link, setLink] = useState<{ url: string; email: string } | null>(null);

  const copy = async () => {
    if (!link) return;
    try {
      await navigator.clipboard.writeText(link.url);
      toast.success("Invite link copied");
    } catch {
      toast.error("Couldn't copy. Select the link and copy it.");
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Invite a teammate</CardTitle>
        <CardDescription>They get a link to join. Send it on WhatsApp or email.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <form
          className="flex flex-col gap-3 sm:flex-row sm:items-end"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate(
              { email, role },
              {
                onSuccess: (r) => {
                  setLink({ url: r.accept_url, email: r.invite.email });
                  setEmail("");
                },
              },
            );
          }}
        >
          <div className="flex-1 space-y-2">
            <Label htmlFor={fid("invite-email")}>Email</Label>
            <Input
              id={fid("invite-email")}
              type="email"
              placeholder="suresh@yourcompany.com"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="space-y-2 sm:w-36">
            <Label htmlFor={fid("invite-role")}>Role</Label>
            <NativeSelect
              id={fid("invite-role")}
              value={role}
              onChange={(e) => setRole(e.target.value as typeof role)}
            >
              <option value="member">Member</option>
              <option value="admin">Admin</option>
              {canInviteOwner && <option value="owner">Owner</option>}
            </NativeSelect>
          </div>
          <Button type="submit" disabled={create.isPending}>
            {create.isPending ? <Loader2Icon className="animate-spin" /> : <UserPlusIcon />} Invite
          </Button>
        </form>
        {create.error && (
          <Alert variant="destructive">
            <AlertDescription>{errorMessage(create.error)}</AlertDescription>
          </Alert>
        )}
        {link && (
          <div className="bg-accent/40 space-y-2 rounded-lg border p-3">
            <p className="text-sm">
              Send this link to <b>{link.email}</b>. It works for 7 days.
            </p>
            <div className="flex gap-2">
              <Input readOnly value={link.url} onFocus={(e) => e.currentTarget.select()} />
              <Button
                type="button"
                variant="outline"
                size="icon"
                onClick={copy}
                aria-label="Copy link"
              >
                <CopyIcon />
              </Button>
            </div>
            <Button variant="link" size="sm" className="px-0" asChild>
              <a
                href={`https://wa.me/?text=${encodeURIComponent(`Join our team on Enquiry Inbox: ${link.url}`)}`}
                target="_blank"
                rel="noreferrer"
              >
                <MessageCircleIcon /> Share on WhatsApp
              </a>
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function Team() {
  const { wid, me, role, isAdmin, isOwner } = useWorkspace();
  const router = useRouter();
  const members = useMembers(wid);
  const invites = useInvites(wid, isAdmin);
  const revoke = useRevokeInvite(wid);
  const remove = useRemoveMember(wid);

  return (
    <>
      <PageHeader title="Team" description="People who can see this workspace's enquiries." />
      <div className="space-y-5">
        {isAdmin && <InviteForm wid={wid} canInviteOwner={isOwner} />}

        <Card className="gap-0 pb-0">
          <CardHeader className="pb-3">
            <CardTitle>Members</CardTitle>
          </CardHeader>
          <CardContent className="px-0">
            {members.isPending ? (
              <div className="px-5 pb-5">
                <ListSkeleton rows={2} />
              </div>
            ) : members.error ? (
              <div className="px-5 pb-5">
                <ErrorState error={members.error} onRetry={() => members.refetch()} />
              </div>
            ) : (
              <ul className="divide-y border-t">
                {members.data.map((m) => {
                  const self = m.user_id === me?.user.id;
                  const canRemove = !self && isAdmin && (m.role !== "owner" || isOwner);
                  return (
                    <li key={m.user_id} className="flex items-center gap-3 px-5 py-3">
                      <Avatar name={m.name} className="size-9" />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-medium">
                          {m.name} {self && <span className="text-muted-foreground">(you)</span>}
                        </div>
                        <div className="text-muted-foreground truncate text-xs">{m.email}</div>
                      </div>
                      <Badge variant={m.role === "member" ? "secondary" : "default"}>
                        {ROLE_LABEL[m.role]}
                      </Badge>
                      {canRemove && (
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label={`Remove ${m.name}`}
                          onClick={() => {
                            if (confirm(`Remove ${m.name} from this workspace?`))
                              remove.mutate(m.user_id, {
                                onError: (e) => toast.error(errorMessage(e)),
                              });
                          }}
                        >
                          <XIcon />
                        </Button>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </CardContent>
        </Card>

        {isAdmin && (invites.data?.length ?? 0) > 0 && (
          <Card className="gap-0 pb-0">
            <CardHeader className="pb-3">
              <CardTitle>Waiting to join</CardTitle>
            </CardHeader>
            <CardContent className="px-0">
              <ul className="divide-y border-t">
                {invites.data?.map((i) => (
                  <li key={i.id} className="flex items-center gap-3 px-5 py-3">
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium">{i.email}</div>
                      <div className="text-muted-foreground text-xs">
                        {ROLE_LABEL[i.role]} · invited {shortDate(i.created_at)}
                      </div>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() =>
                        revoke.mutate(i.id, { onSuccess: () => toast.success("Invite cancelled") })
                      }
                    >
                      Cancel
                    </Button>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        )}

        {role !== "owner" && (
          <Button
            variant="outline"
            onClick={() => {
              if (me && confirm("Leave this workspace? You'll need a new invite to come back."))
                remove.mutate(me.user.id, { onSuccess: () => router.replace("/") });
            }}
          >
            Leave workspace
          </Button>
        )}
      </div>
    </>
  );
}
