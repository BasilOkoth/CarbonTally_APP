const admin = require("firebase-admin");
const serviceAccount = require("./service-account-key.json"); // Path to your key

admin.initializeApp({
  credential: admin.credential.cert(serviceAccount),
  databaseURL: "YOUR_FIREBASE_DB_URL" // Optional but recommended
});

async function approveUser() {
  try {
    await admin.firestore()
      .collection("users")
      .doc("KdxYULovRlffMY7JYUFcIVv0Ofa2")
      .update({ status: "approved" });
    console.log("✅ User approved successfully!");
  } catch (error) {
    console.error("❌ Error:", error.message);
  }
}

approveUser();