// Firebase Messaging Service Worker for MotoBhai
// This file MUST be at the root of the domain for FCM to work

importScripts('https://www.gstatic.com/firebasejs/10.12.0/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/10.12.0/firebase-messaging-compat.js');

firebase.initializeApp({
  apiKey: "AIzaSyAHadMoiOLutcsdWz0qqH7slnSI-YGZXww",
  authDomain: "motobhai-india.firebaseapp.com",
  projectId: "motobhai-india",
  storageBucket: "motobhai-india.firebasestorage.app",
  messagingSenderId: "309222701073",
  appId: "1:309222701073:web:8bb6f9bd67cc5ccc8599b0"
});

const messaging = firebase.messaging();

// Handle background push notifications
messaging.onBackgroundMessage((payload) => {
  const { title, body, icon } = payload.notification || {};
  const notificationTitle = title || '🏍️ MotoBhai';
  const notificationOptions = {
    body: body || 'Chal bhai, ride pe chalte hain!',
    icon: icon || '/icons/icon-192.png',
    badge: '/icons/icon-192.png',
    data: { url: 'https://motobhai.app' },
    vibrate: [200, 100, 200],
    tag: 'motobhai-notification'
  };

  self.registration.showNotification(notificationTitle, notificationOptions);
});

// Handle notification click — open the app
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = event.notification.data?.url || 'https://motobhai.app';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(windowClients => {
      // Focus existing tab if open
      for (const client of windowClients) {
        if (client.url.includes('motobhai') && 'focus' in client) {
          return client.focus();
        }
      }
      // Otherwise open new tab
      return clients.openWindow(url);
    })
  );
});
