"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { RequireAuth } from "@/components/app/require-auth";
import { FullPageSpinner } from "@/components/app/states";
import type { Me } from "@/lib/queries";

const LAST_WORKSPACE_KEY = "e2o:last-workspace";

export function rememberWorkspace(id: string) {
  try {
    localStorage.setItem(LAST_WORKSPACE_KEY, id);
  } catch {
    // storage unavailable (private mode); fine.
  }
}

function Redirect({ me }: { me: Me }) {
  const router = useRouter();
  useEffect(() => {
    if (me.workspaces.length === 0) {
      router.replace("/onboarding");
      return;
    }
    let last: string | null = null;
    try {
      last = localStorage.getItem(LAST_WORKSPACE_KEY);
    } catch {
      last = null;
    }
    const target = me.workspaces.find((w) => w.id === last) ?? me.workspaces[0];
    router.replace(`/w/${target.id}`);
  }, [me, router]);
  return <FullPageSpinner />;
}

export function HomeRedirect() {
  return <RequireAuth>{(me) => <Redirect me={me} />}</RequireAuth>;
}
