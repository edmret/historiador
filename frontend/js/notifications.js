// Web Push Notifications
const NOTIFICATIONS = {
  async init() {
    if (!("Notification" in window) || !("serviceWorker" in navigator)) {
      console.log("Push notifications not supported");
      return;
    }
    if (Notification.permission === "granted") {
      await this.subscribe();
    } else if (Notification.permission !== "denied") {
      const permission = await Notification.requestPermission();
      if (permission === "granted") await this.subscribe();
    }
  },

  async subscribe() {
    try {
      const registration = await navigator.serviceWorker.ready;
      const sub = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: this.urlBase64ToUint8Array(
          "BIs9YnKX9NQEmEnxBjtQZs7pGNjEz4RWYXEDb7EBtXyWg_HJ1_3ZcY6fBnVPlF5B_eFvhCxOTJ_J5rz44JiW7Pc"
        ),
      });
      await API.subscribePush({
        endpoint: sub.endpoint,
        p256dh: this.arrayBufferToBase64(sub.getKey("p256dh")),
        auth: this.arrayBufferToBase64(sub.getKey("auth")),
      });
      console.log("Push subscription active");
    } catch (err) {
      console.warn("Push subscription failed:", err);
    }
  },

  urlBase64ToUint8Array(base64String) {
    const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    const rawData = window.atob(base64);
    return Uint8Array.from([...rawData].map((c) => c.charCodeAt(0)));
  },

  arrayBufferToBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = "";
    for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
    return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  },
};