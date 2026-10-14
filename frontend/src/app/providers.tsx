"use client";

import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";

import { ApiError } from "@/lib/api/client";

function makeClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 20_000,
        retry: (count, error) =>
          !(error instanceof ApiError && [401, 403, 404, 410].includes(error.status)) && count < 2,
      },
    },
  });
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(makeClient);
  return (
    <QueryClientProvider client={client}>
      {children}
      <Toaster position="top-center" richColors closeButton />
    </QueryClientProvider>
  );
}
