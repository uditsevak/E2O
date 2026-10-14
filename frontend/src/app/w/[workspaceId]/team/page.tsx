import { Suspense } from "react";
import type { Metadata } from "next";

import { PageSkeleton } from "@/components/app/states";
import { Team } from "@/components/team/team";

export const metadata: Metadata = { title: "Team" };

export default function TeamPage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <Team />
    </Suspense>
  );
}
