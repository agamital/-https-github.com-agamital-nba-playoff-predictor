import React from 'react'
import ReactDOM from 'react-dom/client'
import { PersistQueryClientProvider } from '@tanstack/react-query-persist-client'
import App from './App.jsx'
import './index.css'
import queryClient, { localStoragePersister } from './lib/queryClient.js';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <PersistQueryClientProvider
      client={queryClient}
      persistOptions={{
        persister: localStoragePersister,
        maxAge: 24 * 60 * 60 * 1000,    // hydrate cached data up to 24 h old
        dehydrateOptions: {
          // Only persist successful queries — never cache errors or loading state
          shouldDehydrateQuery: (query) => query.state.status === 'success',
        },
      }}
    >
      <App />
    </PersistQueryClientProvider>
  </React.StrictMode>,
)

// Register PWA service worker (separate from OneSignal worker)
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  });
}
