import { Suspense } from "react";
import type { Metadata } from "next";

import { PageSkeleton } from "@/components/app/states";
import { ConnectMailbox } from "@/components/mailboxes/connect-mailbox";

export const metadata: Metadata = { title: "Connect a mailbox" };

export default function ConnectMailboxPage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <ConnectMailbox />
    </Suspense>
  );
}
