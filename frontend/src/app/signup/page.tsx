import { Suspense } from "react";
import type { Metadata } from "next";

import { FullPageSpinner } from "@/components/app/states";
import { SignupForm } from "@/components/auth/forms";

export const metadata: Metadata = { title: "Create account" };

export default function SignupPage() {
  return (
    <Suspense fallback={<FullPageSpinner />}>
      <SignupForm />
    </Suspense>
  );
}
