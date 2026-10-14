import { Suspense } from "react";

import { FullPageSpinner } from "@/components/app/states";

import { HomeRedirect } from "./home-redirect";

export default function Home() {
  return (
    <Suspense fallback={<FullPageSpinner />}>
      <HomeRedirect />
    </Suspense>
  );
}
