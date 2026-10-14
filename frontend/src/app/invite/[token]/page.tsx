import { Suspense } from "react";
import type { Metadata } from "next";

import { FullPageSpinner } from "@/components/app/states";

import { AcceptInvite } from "./accept-invite";

export const metadata: Metadata = { title: "Join your team" };

export default function InvitePage() {
  return (
    <Suspense fallback={<FullPageSpinner />}>
      <AcceptInvite />
    </Suspense>
  );
}
