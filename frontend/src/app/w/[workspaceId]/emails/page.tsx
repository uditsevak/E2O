import { Suspense } from "react";
import type { Metadata } from "next";

import { PageSkeleton } from "@/components/app/states";
import { EmailList } from "@/components/emails/email-list";

export const metadata: Metadata = { title: "Emails" };

export default function EmailsPage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <EmailList />
    </Suspense>
  );
}
