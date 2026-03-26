import { QueryClient } from '@tanstack/react-query';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000,      // 5 min — serve from cache without refetch
      gcTime:    30 * 60 * 1000,     // 30 min — keep in memory after unmount
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

export default queryClient;
