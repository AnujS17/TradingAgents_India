'use client';

import { useQuery } from '@tanstack/react-query';
import { getRun, type RunDetail } from './api-client/client';

const TERMINAL_STATUSES: RunDetail['status'][] = ['completed', 'failed', 'cancelled'];

export function usePollRun(runId: string | undefined, initialData?: RunDetail) {
  return useQuery({
    queryKey: ['run', runId],
    queryFn: () => getRun(runId as string),
    enabled: Boolean(runId),
    initialData,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status && TERMINAL_STATUSES.includes(status)) return false;
      return 4000;
    },
  });
}
