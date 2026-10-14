import { Suspense } from "react";
import type { Metadata } from "next";

import { FullPageSpinner } from "@/components/app/states";

import { Onboarding } from "./onboarding";

export const metadata: Metadata = { title: "Set up your business" };

export default function OnboardingPage() {
  return (
    <Suspense fallback={<FullPageSpinner />}>
      <Onboarding />
    </Suspense>
  );
}
