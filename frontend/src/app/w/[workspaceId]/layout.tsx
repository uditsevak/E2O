import { Suspense } from "react";

import { AppShell } from "@/components/app/app-shell";
import { FullPageSpinner } from "@/components/app/states";

export default function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  return (
    <Suspense fallback={<FullPageSpinner />}>
      <AppShell>{children}</AppShell>
    </Suspense>
  );
}
