"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactNode, useEffect, useState } from "react";
import { startIdleTimer, stopIdleTimer, getUserMeta } from "@/lib/auth";
import { useBlockStrayFileDrops } from "@/lib/hooks/use-block-stray-file-drops";
import { TooltipProvider } from "@/components/ui/tooltip";
import { installDevMocks } from "@/lib/dev-mock/mock-api";

// Local design-preview mocks — only active when NEXT_PUBLIC_MOCK_API=1 is set
// in a gitignored .env.local. Installed at module load (before any query can
// fire), not in an effect, so nothing races it. No-op in every other build.
if (typeof window !== "undefined" && process.env.NEXT_PUBLIC_MOCK_API === "1") {
  installDevMocks();
}

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

  return (
    <QueryClientProvider client={client}>
      <TooltipProvider delayDuration={300}>{children}</TooltipProvider>
    </QueryClientProvider>
  );
}
