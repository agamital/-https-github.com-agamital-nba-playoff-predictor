import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import './index.css'
import OneSignal from 'react-onesignal';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)

// Register service worker for PWA
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  });
}

// Initialize OneSignal push notifications (non-blocking)
OneSignal.init({
  appId: import.meta.env.VITE_ONESIGNAL_APP_ID || 'c69b4c3e-79d1-48a4-8815-3ceabc1eae70',
  allowLocalhostAsSecureOrigin: true,
  notifyButton: { enable: false },
  serviceWorkerParam: { scope: '/' },
}).catch(() => {});
