const { initializeApp } = require("firebase-admin/app");
const { getFirestore } = require("firebase-admin/firestore");
const { getMessaging } = require("firebase-admin/messaging");
const { onSchedule } = require("firebase-functions/v2/scheduler");
const { onCall, HttpsError } = require("firebase-functions/v2/https");
const { logger } = require("firebase-functions");

initializeApp();

// Admin UIDs allowed to send custom notifications
const ADMIN_UIDS = ['ADMIN_UID_HERE'];

const db = getFirestore();
const messaging = getMessaging();

// ─── Token Helpers ───────────────────────────────────────────────────────────

/**
 * Fetches all FCM tokens from Firestore.
 * @returns {Promise<Array<{token: string, docId: string}>>}
 */
async function getAllTokens() {
  const snapshot = await db.collection("fcmTokens").get();
  const tokens = [];
  snapshot.forEach((doc) => {
    const data = doc.data();
    if (data.token) {
      tokens.push({ token: data.token, docId: doc.id });
    }
  });
  return tokens;
}

/**
 * Sends a notification to all tokens and cleans up stale ones.
 * @param {string} title
 * @param {string} body
 */
async function sendToAllTokens(title, body) {
  const tokens = await getAllTokens();
  if (tokens.length === 0) {
    logger.info("No FCM tokens found. Skipping notification.");
    return { success: 0, failure: 0 };
  }

  logger.info(`Sending notification to ${tokens.length} token(s): "${title}"`);

  let successCount = 0;
  let failureCount = 0;

  // Send individually so we can map failures to specific tokens for cleanup
  const sendPromises = tokens.map(async ({ token, docId }) => {
    try {
      await messaging.send({
        token,
        notification: { title, body },
        android: {
          priority: "high",
          notification: { channelId: "motobhai_rides" },
        },
        apns: {
          payload: { aps: { sound: "default" } },
        },
      });
      successCount++;
    } catch (error) {
      failureCount++;
      logger.error(`Failed to send to token ${docId}:`, error.code);

      // Clean up stale tokens
      if (
        error.code === "messaging/registration-token-not-registered" ||
        error.code === "messaging/invalid-registration-token"
      ) {
        logger.info(`Deleting stale token: ${docId}`);
        await db.collection("fcmTokens").doc(docId).delete();
      }
    }
  });

  await Promise.all(sendPromises);
  logger.info(`Notification sent. Success: ${successCount}, Failure: ${failureCount}`);
  return { success: successCount, failure: failureCount };
}

// ─── Weekend Ride Messages ───────────────────────────────────────────────────

const WEEKEND_MESSAGES = [
  {
    title: "🏍️ Chal Bhai, Ride Par!",
    body: "Haanji goodmorning! Weekend hai, kahan ghoomne chalein? Trip plan kar le MotoBhai se.",
  },
  {
    title: "☀️ Subah Ho Gayi Mamu!",
    body: "Chai pi, gear pehen, aur nikal ja! MotoBhai ne route ready rakha hai tere liye.",
  },
  {
    title: "🛣️ Highway Bula Raha Hai!",
    body: "Weekend waste mat kar bhai. Ek ride plan kar, dost bula, aur nikal!",
  },
  {
    title: "🏔️ Pahaadon Ka Plan Bana?",
    body: "Bhai Saturday/Sunday hai! Chal kahi ghoomke aate hain. Open MotoBhai, plan karte hain.",
  },
  {
    title: "🌅 Sunrise Ride Chalein?",
    body: "Early morning ride ka maza hi alag hai. MotoBhai se route plan kar aur nikal!",
  },
  {
    title: "☕ Chai + Ride = Perfect Weekend",
    body: "Uth ja bhai! Chai pe le, bike start kar, aur MotoBhai pe trip plan kar.",
  },
];

// ─── Festival Calendar & Messages ────────────────────────────────────────────

// Dates in MM-DD format for 2025-2026
const FESTIVAL_CALENDAR = {
  // ── 2025 ──
  "2025-01-13": "Lohri",
  "2025-01-14": "Makar Sankranti",
  "2025-01-14": "Pongal",
  "2025-01-26": "Republic Day",
  "2025-03-14": "Holi",
  "2025-03-31": "Eid",
  "2025-04-13": "Baisakhi",
  "2025-08-09": "Raksha Bandhan",
  "2025-08-15": "Independence Day",
  "2025-08-16": "Janmashtami",
  "2025-08-27": "Ganesh Chaturthi",
  "2025-09-02": "Onam",
  "2025-09-22": "Navratri Start",
  "2025-10-02": "Dussehra",
  "2025-10-20": "Diwali",
  "2025-11-05": "Guru Nanak Jayanti",
  "2025-12-25": "Christmas",
  "2025-12-31": "New Year Eve",
  // ── 2026 ──
  "2026-01-01": "New Year",
  "2026-01-13": "Lohri",
  "2026-01-14": "Makar Sankranti",
  "2026-01-14": "Pongal",
  "2026-01-26": "Republic Day",
  "2026-03-04": "Holi",
  "2026-03-20": "Eid",
  "2026-04-13": "Baisakhi",
  "2026-07-29": "Raksha Bandhan",
  "2026-08-06": "Janmashtami",
  "2026-08-15": "Independence Day",
  "2026-08-17": "Ganesh Chaturthi",
  "2026-08-21": "Onam",
  "2026-10-11": "Navratri Start",
  "2026-10-20": "Dussehra",
  "2026-11-08": "Diwali",
  "2026-11-24": "Guru Nanak Jayanti",
  "2026-12-25": "Christmas",
  "2026-12-31": "New Year Eve",
};

const FESTIVAL_MESSAGES = {
  "Holi": {
    title: "🎨 Happy Holi Bhai!",
    body: "Rang lagao, phir ride pe chalo! MotoBhai pe plan karo aaj ka trip.",
  },
  "Diwali": {
    title: "🪔 Happy Diwali!",
    body: "Patake nahi, engine ki awaaz sunao! Diwali ride ka plan bana MotoBhai pe.",
  },
  "Independence Day": {
    title: "🇮🇳 Happy Independence Day!",
    body: "Tiranga leke ride par chal! Desh ke liye ek patriotic ride plan kar MotoBhai se.",
  },
  "Republic Day": {
    title: "🇮🇳 Happy Republic Day!",
    body: "Jai Hind! Aaj tiranga leke ek ride maar bhai. MotoBhai pe plan kar.",
  },
  "Ganesh Chaturthi": {
    title: "🙏 Ganpati Bappa Morya!",
    body: "Ganesh Chaturthi ki badhai! Darshan ke baad ek ride plan kar MotoBhai se.",
  },
  "Navratri Start": {
    title: "🔱 Jai Mata Di! Navratri Shuru!",
    body: "Navratri ki badhai bhai! 9 din, 9 rides? MotoBhai pe plan karo!",
  },
  "Eid": {
    title: "🌙 Eid Mubarak Bhai!",
    body: "Eid ki bahut mubarak! Sewaiyaan khao aur phir ek chill ride pe niklo.",
  },
  "Christmas": {
    title: "🎄 Merry Christmas Bhai!",
    body: "Christmas ki badhai! Thandi hawa mein ek ride ka maza le MotoBhai ke saath.",
  },
  "New Year": {
    title: "🎉 Happy New Year Bhai!",
    body: "Naya saal, nayi rides! 2026 mein MotoBhai ke saath zabardast trips plan kar.",
  },
  "New Year Eve": {
    title: "🎉 Happy New Year Eve!",
    body: "Saal ka aakhri din! Ek epic ride se goodbye bol is saal ko. MotoBhai pe plan kar.",
  },
  "Makar Sankranti": {
    title: "🪁 Happy Makar Sankranti!",
    body: "Patang toh udaai, ab bike bhi udaa! MotoBhai se plan kar ek mast ride.",
  },
  "Pongal": {
    title: "🌾 Happy Pongal!",
    body: "Pongal ki badhai! Aaj ek ride pe nikal aur MotoBhai se route plan kar.",
  },
  "Baisakhi": {
    title: "🌾 Happy Baisakhi!",
    body: "Baisakhi di lakh lakh vadhaiyaan! Bhangra ke baad bike pe nikal bhai.",
  },
  "Lohri": {
    title: "🔥 Happy Lohri!",
    body: "Lohri ki badhai! Aag ke paas baith ke next ride plan kar MotoBhai pe.",
  },
  "Raksha Bandhan": {
    title: "🧵 Happy Raksha Bandhan!",
    body: "Behen se rakhi bandhwa, phir ek ride pe nikal! MotoBhai pe plan kar.",
  },
  "Janmashtami": {
    title: "🦚 Happy Janmashtami!",
    body: "Jai Shri Krishna! Mathura-Vrindavan ride ka plan bana MotoBhai se!",
  },
  "Dussehra": {
    title: "🏹 Happy Dussehra!",
    body: "Burai pe achai ki jeet! Aaj ek vijay ride maar bhai. MotoBhai pe plan kar.",
  },
  "Onam": {
    title: "🌸 Happy Onam!",
    body: "Onam ashamsakal! Kerala ride ka sapna poora kar MotoBhai ke saath.",
  },
  "Guru Nanak Jayanti": {
    title: "🙏 Guru Nanak Jayanti Di Vadhaiyaan!",
    body: "Waheguru! Aaj gurudwara jao aur phir ek peaceful ride pe niklo.",
  },
};

const GENERIC_FESTIVAL_MESSAGE = {
  title: "🎉 Festival Vibes!",
  body: "Long weekend hai? Trip plan kar MotoBhai se! Festival pe ride ka maza alag hai.",
};

// ─── Helper: Get today's date string in IST ──────────────────────────────────

function getTodayIST() {
  const now = new Date();
  // Convert to IST
  const istOffset = 5.5 * 60 * 60 * 1000;
  const istDate = new Date(now.getTime() + istOffset + now.getTimezoneOffset() * 60 * 1000);
  const year = istDate.getFullYear();
  const month = String(istDate.getMonth() + 1).padStart(2, "0");
  const day = String(istDate.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

// ─── Cloud Function: weekendRide ─────────────────────────────────────────────
// Runs every Saturday & Sunday at 7:30 AM IST

exports.weekendRide = onSchedule(
  {
    schedule: "30 7 * * 0,6",
    timeZone: "Asia/Kolkata",
    retryCount: 1,
  },
  async (event) => {
    logger.info("weekendRide triggered");

    const randomIndex = Math.floor(Math.random() * WEEKEND_MESSAGES.length);
    const message = WEEKEND_MESSAGES[randomIndex];

    const result = await sendToAllTokens(message.title, message.body);
    logger.info("weekendRide completed", result);
  },
);

// ─── Cloud Function: festivalRide ────────────────────────────────────────────
// Runs daily at 8 AM IST, checks if today is a festival

exports.festivalRide = onSchedule(
  {
    schedule: "0 8 * * *",
    timeZone: "Asia/Kolkata",
    retryCount: 1,
  },
  async (event) => {
    const todayStr = getTodayIST();
    logger.info(`festivalRide triggered. Today: ${todayStr}`);

    const festivalName = FESTIVAL_CALENDAR[todayStr];
    if (!festivalName) {
      logger.info("No festival today. Skipping.");
      return;
    }

    logger.info(`Today is ${festivalName}! Sending festival notification.`);

    const festivalMsg = FESTIVAL_MESSAGES[festivalName] || GENERIC_FESTIVAL_MESSAGE;
    const result = await sendToAllTokens(festivalMsg.title, festivalMsg.body);
    logger.info("festivalRide completed", result);
  },
);

// ─── Cloud Function: sendCustomNotification ─────────────────────────────────
// HTTPS Callable – for admin use (manual push)

exports.sendCustomNotification = onCall(
  {
    enforceAppCheck: false,
  },
  async (request) => {
    // Auth gate: only admins can send notifications
    if (!request.auth || !ADMIN_UIDS.includes(request.auth.uid)) {
      throw new HttpsError(
        "permission-denied",
        "Only admins can send notifications.",
      );
    }

    const { title, body } = request.data;

    if (!title || !body) {
      throw new HttpsError(
        "invalid-argument",
        "Both 'title' and 'body' are required.",
      );
    }

    logger.info(`sendCustomNotification called: "${title}" / "${body}"`);

    const result = await sendToAllTokens(title, body);
    return {
      message: "Notification sent successfully.",
      ...result,
    };
  },
);
