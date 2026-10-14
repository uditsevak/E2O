"use client";

import { useEffect } from "react";
import { useParams } from "next/navigation";

import { rememberWorkspace } from "@/app/home-redirect";
import { useMe } from "@/lib/queries";

/** The current workspace (from the URL) and the user's role in it. Only use under AppShell. */
export function useWorkspace() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const me = useMe();
  const workspace = me.data?.workspaces.find((w) => w.id === workspaceId);
  useEffect(() => {
    if (workspace) rememberWorkspace(workspace.id);
  }, [workspace]);
  const role = workspace?.role ?? "member";
  return {
    wid: workspaceId,
    workspace,
    me: me.data,
    role,
    isAdmin: role === "admin" || role === "owner",
    isOwner: role === "owner",
  };
}
