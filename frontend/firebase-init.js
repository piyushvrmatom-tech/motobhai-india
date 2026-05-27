// Moto Bhai India - Firebase Web SDK initialization
// Project: motobhai-india
// App: Moto Bhai Web

import { initializeApp } from "https://www.gstatic.com/firebasejs/10.12.0/firebase-app.js";
import { getAuth } from "https://www.gstatic.com/firebasejs/10.12.0/firebase-auth.js";
import { getFirestore } from "https://www.gstatic.com/firebasejs/10.12.0/firebase-firestore.js";
import { getAnalytics, isSupported } from "https://www.gstatic.com/firebasejs/10.12.0/firebase-analytics.js";

const firebaseConfig = {
  apiKey: "AIzaSyAHadMoiOLutcsdWz0qqH7slnSI-YGZXww",
  authDomain: "motobhai-india.firebaseapp.com",
  projectId: "motobhai-india",
  storageBucket: "motobhai-india.firebasestorage.app",
  messagingSenderId: "309222701073",
  appId: "1:309222701073:web:8bb6f9bd67cc5ccc8599b0"
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
