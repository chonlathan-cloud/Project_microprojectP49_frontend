import { getApp, getApps, initializeApp } from "firebase/app";
import {
  type Auth,
  browserLocalPersistence,
  browserPopupRedirectResolver,
  browserSessionPersistence,
  getAuth,
  inMemoryPersistence,
  initializeAuth
} from "firebase/auth";

const firebaseConfig = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY ?? "AIzaSyB-gPOVkvzmSbs_V1MTv0aiTD6Smso0lTI",
  authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN ?? "the49-487609.firebaseapp.com",
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID ?? "the49-487609",
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID ?? "1:439060579730:web:19e00bdaef54f1aa566d4b"
};

let authInstance: Auth | undefined;

export function getFirebaseAuth() {
  if (!firebaseConfig.apiKey || !firebaseConfig.authDomain || !firebaseConfig.appId) {
    throw new Error("Firebase Web configuration is incomplete");
  }
  if (authInstance) return authInstance;

  const app = getApps().length ? getApp() : initializeApp(firebaseConfig);
  // Prefer durable first-party persistence for the popup flow. Session and
  // memory persistence keep authentication usable in privacy-restricted tabs.
  try {
    authInstance = initializeAuth(app, {
      persistence: [
        browserLocalPersistence,
        browserSessionPersistence,
        inMemoryPersistence
      ],
      popupRedirectResolver: browserPopupRedirectResolver
    });
  } catch {
    // Handles React development remounts and hot reloads after Auth has
    // already been initialized for this Firebase app.
    authInstance = getAuth(app);
  }
  return authInstance;
}
