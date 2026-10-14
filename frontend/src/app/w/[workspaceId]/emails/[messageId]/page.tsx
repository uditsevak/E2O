import { Suspense } from "react";
import type { Metadata } from "next";

import { PageSkeleton } from "@/components/app/states";
import { EmailDetail } from "@/components/emails/email-detail";

export const metadata: Metadata = { title: "Email" };

export default function EmailPage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <EmailDetail />
    </Suspense>
  );
}
