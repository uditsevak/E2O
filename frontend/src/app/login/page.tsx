import { Suspense } from "react";
import type { Metadata } from "next";

import { FullPageSpinner } from "@/components/app/states";
import { LoginForm } from "@/components/auth/forms";

export const metadata: Metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <Suspense fallback={<FullPageSpinner />}>
      <LoginForm />
    </Suspense>
  );
}
