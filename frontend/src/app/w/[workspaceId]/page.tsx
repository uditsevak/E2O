import { Suspense } from "react";
import type { Metadata } from "next";

import { PageSkeleton } from "@/components/app/states";
import { Overview } from "@/components/overview/overview";

export const metadata: Metadata = { title: "Overview" };

export default function OverviewPage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <Overview />
    </Suspense>
  );
}
