'use client';

import * as React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { AppToaster } from '@/components/shared/app-toaster';
import { UiFeedback } from '@/components/shared/ui-feedback';
import { TooltipProvider } from '@/components/ui/tooltip';
import { uiFeedback } from '@/lib/api';

export function Providers({ children }: { children: React.ReactNode }) {
  // One retry keeps a flaky request from flashing an error, without making a real outage slow to surface.
  // 403 and 404 are answers, not flakes: retrying them only delays the "belongs to another team" or not-found state.
  const [client] = React.useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { retry: (failures, e) => ![403, 404].includes((e as { status?: number }).status ?? 0) && failures < 1, staleTime: 30_000 } },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <TooltipProvider delayDuration={200}>
        {children}
        <AppToaster />
        <UiFeedback enabled={uiFeedback} />
      </TooltipProvider>
    </QueryClientProvider>
  );
}
