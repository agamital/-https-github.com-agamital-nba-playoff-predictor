import { QueryClient } from '@tanstack/react-query';
import { createSyncStoragePersister } from '@tanstack/query-sync-storage-persister';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 2 * 60 * 1000,      // 2 min — during playoffs data changes frequently
      gcTime:    24 * 60 * 60 * 1000, // 24 h — keep in memory/localStorage
      refetchOnWindowFocus: true,     // always re-check when user tabs back in
      retry: 1,
    },
  },
});

// Persist query cache to localStorage so the app loads instantly on revisit.
// Only successful queries are persisted; errors are never written to disk.
export const localStoragePersister = createSyncStoragePersister({
  storage: typeof window !== 'undefined' ? window.localStorage : null,
  key: 'nba-playoff-rq-cache',
  throttleTime: 1000,   // debounce writes — max 1 write/s
});

export default queryClient;
