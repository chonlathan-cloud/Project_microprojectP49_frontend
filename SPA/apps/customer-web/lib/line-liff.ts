export type LiffClient = {
  init: (options: { liffId: string }) => Promise<void>;
  isLoggedIn: () => boolean;
  isInClient: () => boolean;
  login: (options?: { redirectUri?: string }) => void;
  getIDToken: () => string | null;
  getFriendship: () => Promise<{ friendFlag: boolean }>;
  requestFriendship?: () => Promise<void>;
  isApiAvailable?: (apiName: string) => boolean;
  closeWindow?: () => void;
};

declare global {
  interface Window {
    liff?: LiffClient;
  }
}

export function loadLiff(): Promise<LiffClient> {
  if (window.liff) return Promise.resolve(window.liff);
  return new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>("script[data-spa-liff]");
    const script = existing ?? document.createElement("script");
    script.addEventListener("load", () => window.liff ? resolve(window.liff) : reject(new Error("LIFF SDK unavailable")), { once: true });
    script.addEventListener("error", () => reject(new Error("LIFF SDK unavailable")), { once: true });
    if (!existing) {
      script.src = "https://static.line-scdn.net/liff/edge/2/sdk.js";
      script.async = true;
      script.dataset.spaLiff = "true";
      document.head.appendChild(script);
    }
  });
}
