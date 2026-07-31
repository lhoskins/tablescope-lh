"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactNode, useEffect, useState } from "react";
import { startIdleTimer, stopIdleTimer, getUserMeta } from "@/lib/auth";
import { useBlockStrayFileDrops } from "@/lib/hooks/use-block-stray-file-drops";

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: 1,
            staleTime: 30_000,
            refetchOnWindowFocus: false,
          },
        },
      })
  );

  // Stop the browser from navigating when a file is dropped outside a dropzone.
  useBlockStrayFileDrops();

  // Start idle timer only when user is logged in
  useEffect(() => {
    const meta = getUserMeta();
    if (meta) {
      startIdleTimer();
    }
    return () => stopIdleTimer();
  }, []);

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
