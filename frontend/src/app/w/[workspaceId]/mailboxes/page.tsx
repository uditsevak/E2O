import { Suspense } from "react";
import type { Metadata } from "next";

import { PageSkeleton } from "@/components/app/states";
import { MailboxList } from "@/components/mailboxes/mailbox-list";

export const metadata: Metadata = { title: "Mailboxes" };

export default function MailboxesPage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <MailboxList />
    </Suspense>
  );
}
