// Moto Bhai India - Firebase Web SDK initialization
// Project: motobhai-app
// App: Moto Bhai Web

import { initializeApp } from "https://www.gstatic.com/firebasejs/10.12.0/firebase-app.js";
import { getAuth } from "https://www.gstatic.com/firebasejs/10.12.0/firebase-auth.js";
import { getFirestore } from "https://www.gstatic.com/firebasejs/10.12.0/firebase-firestore.js";
import { getAnalytics, isSupported } from "https://www.gstatic.com/firebasejs/10.12.0/firebase-analytics.js";

const firebaseConfig = {
  apiKey: "AIzaSyDgojgJrScBtyl5mCWq8C4HuBr0k3RgiYM",
  authDomain: "motobhai-app.firebaseapp.com",
  projectId: "motobhai-app",
  storageBucket: "motobhai-app.firebasestorage.app",
  messagingSenderId: "783191998359",
  appId: "1:783191998359:web:8c5c32e266d104766b4ed2"
};

const app = initializeApp(firebaseConfig);
const auth = getAuth(app);
const db = getFirestore(app);

// Expose to window for non-module scripts in the page
window.firebaseApp = app;
window.firebaseAuth = auth;
window.firebaseDb = db;

// Analytics only on https:// (not file://) and where supported
isSupported().then((ok) => {
  if (ok && location.protocol.startsWith("http")) {
    window.firebaseAnalytics = getAnalytics(app);
    console.log("[Firebase] analytics enabled");
  }
}).catch(() => {});

console.log("[Firebase] initialized:", firebaseConfig.projectId);
