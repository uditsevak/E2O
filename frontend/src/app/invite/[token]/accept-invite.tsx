"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Loader2Icon } from "lucide-react";

import { FullPageSpinner } from "@/components/app/states";
import { AuthLayout } from "@/components/auth/auth-layout";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ApiError, errorMessage } from "@/lib/api/client";
import { useAcceptInvite, useInvitePreview, useMe } from "@/lib/queries";

export function AcceptInvite() {
  const { token } = useParams<{ token: string }>();
  const router = useRouter();
  const preview = useInvitePreview(token);
  const me = useMe();
  const accept = useAcceptInvite();
  const here = `/invite/${token}`;

  if (preview.isPending || me.isPending) return <FullPageSpinner />;
  if (preview.error) {
    return (
      <AuthLayout title="Invite not found">
        <p className="text-muted-foreground text-sm">{errorMessage(preview.error)}</p>
      </AuthLayout>
    );
  }

  const invite = preview.data;
  const signedIn = !(me.error instanceof ApiError && me.error.status === 401) && !!me.data;

  return (
    <AuthLayout
      title={`Join ${invite.workspace_name}`}
      subtitle={
        <>
          {invite.invited_by ?? "Someone"} invited <b>{invite.email}</b> to join as{" "}
          {invite.role === "member" ? "a team member" : `an ${invite.role}`}.
        </>
      }
    >
      {!invite.valid ? (
        <Alert variant="destructive">
          <AlertDescription>{invite.reason}</AlertDescription>
        </Alert>
      ) : signedIn ? (
        <div className="space-y-4">
          {accept.error && (
            <Alert variant="destructive">
              <AlertDescription>{errorMessage(accept.error)}</AlertDescription>
            </Alert>
          )}
          <p className="text-muted-foreground text-sm">
            Signed in as <b>{me.data?.user.email}</b>
          </p>
          <Button
            className="w-full"
            disabled={accept.isPending}
            onClick={() =>
              accept.mutate(token, { onSuccess: (ws) => router.replace(`/w/${ws.id}`) })
            }
          >
            {accept.isPending && <Loader2Icon className="animate-spin" />} Join{" "}
            {invite.workspace_name}
          </Button>
        </div>
      ) : (
        <div className="space-y-3">
          <Button className="w-full" asChild>
            <Link href={`/signup?next=${encodeURIComponent(here)}`}>Create an account to join</Link>
          </Button>
          <Button variant="outline" className="w-full" asChild>
            <Link href={`/login?next=${encodeURIComponent(here)}`}>I already have an account</Link>
          </Button>
          <p className="text-muted-foreground text-xs">
            Use {invite.email} so we can match the invite.
          </p>
        </div>
      )}
    </AuthLayout>
  );
}
