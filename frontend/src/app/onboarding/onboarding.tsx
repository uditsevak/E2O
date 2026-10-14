"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2Icon } from "lucide-react";

import { RequireAuth } from "@/components/app/require-auth";
import { AuthLayout } from "@/components/auth/auth-layout";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { errorMessage } from "@/lib/api/client";
import { useCreateWorkspace, type Me } from "@/lib/queries";
import { useFieldId } from "@/lib/use-field-id";

function CreateWorkspace({ me }: { me: Me }) {
  const fid = useFieldId();
  const router = useRouter();
  const create = useCreateWorkspace();
  const [name, setName] = useState("");
  const first = me.workspaces.length === 0;

  return (
    <AuthLayout
      title={first ? `Welcome, ${me.user.name.split(" ")[0]}` : "Add another business"}
      subtitle="What is your business called? You can invite your team next."
    >
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate(name, {
            onSuccess: (ws) => router.replace(`/w/${ws.id}/mailboxes/connect`),
          });
        }}
      >
        {create.error && (
          <Alert variant="destructive">
            <AlertDescription>{errorMessage(create.error)}</AlertDescription>
          </Alert>
        )}
        <div className="space-y-2">
          <Label htmlFor={fid("name")}>Business name</Label>
          <Input
            id={fid("name")}
            placeholder="e.g. DC Engineering"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <Button type="submit" className="w-full" disabled={create.isPending}>
          {create.isPending && <Loader2Icon className="animate-spin" />} Continue
        </Button>
      </form>
    </AuthLayout>
  );
}

export function Onboarding() {
  return <RequireAuth>{(me) => <CreateWorkspace me={me} />}</RequireAuth>;
}
