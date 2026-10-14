"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";

import { ApiError } from "@/lib/api/client";
import { useMe, type Me } from "@/lib/queries";

import { ErrorState, FullPageSpinner } from "./states";

/** Renders children only for a signed-in user; otherwise sends them to /login. */
export function RequireAuth({ children }: { children: (me: Me) => React.ReactNode }) {
  const me = useMe();
  const router = useRouter();
  const pathname = usePathname();
  const unauthenticated = me.error instanceof ApiError && me.error.status === 401;

  useEffect(() => {
    if (unauthenticated) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [unauthenticated, pathname, router]);

  if (me.isPending || unauthenticated) return <FullPageSpinner />;
  if (me.error) return <ErrorState error={me.error} onRetry={() => me.refetch()} />;
  return <>{children(me.data)}</>;
}
