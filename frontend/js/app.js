// Historiador Router & App Entry
const Router = {
  routes: {},

  register(path, handler) {
    this.routes[path] = handler;
  },

  navigate(path) {
    window.location.hash = "#" + path;
  },

  getCurrentPath() {
    const hash = window.location.hash.slice(1) || "/new";
    return hash;
  },

  async resolve() {
    const path = this.getCurrentPath();

    // Auth guard: redirect to login if not authenticated (skip for login itself)
    if (path !== "/login") {
      const authConfig = await AUTH.getConfig();
      const stytchConfigured = authConfig && authConfig.stytch_configured;
      if (stytchConfigured && !AUTH.isAuthenticated()) {
        this.navigate("login");
        return;
      }
    }

    this.updateNav(path);

    // Try exact match first
    if (this.routes[path]) {
      await this.routes[path]();
      return;
    }

    // Try parameterized routes
    for (const [pattern, handler] of Object.entries(this.routes)) {
      const regex = new RegExp("^" + pattern.replace(/:\\w+/g, "([^/]+)") + "$");
      const match = path.match(regex);
      if (match) {
        const params = match.slice(1);
        await handler(...params);
        return;
      }
    }

    // Fallback
    await this.routes["/new"]();
  },

  updateNav(path) {
    document.querySelectorAll("[data-route]").forEach((a) => {
      const route = a.getAttribute("data-route");
      a.classList.toggle("active", path.includes(route));
    });
  },
};

// Register routes
Router.register("/login", () => LoginPage.render());
Router.register("/new", () => TopicForm.render());
Router.register("/kanban", () => Kanban.render());
Router.register("/kanban/:topicId", (topicId) => Kanban.render(topicId));
Router.register("/scoping/:topicId", (topicId) => ScopingChat.render(topicId));
Router.register("/subtopics/:topicId", (topicId) => SubtopicSelector.render(topicId));
Router.register("/history/:historyId", (historyId) => HistoryViewer.render(historyId));
Router.register("/profiles", () => ProfileManager.render());
Router.register("/settings", () => SettingsPage.render());

// Handle hash changes
window.addEventListener("hashchange", () => Router.resolve());

// Boot
window.addEventListener("DOMContentLoaded", async () => {
  // Register service worker
  if ("serviceWorker" in navigator) {
    try {
      await navigator.serviceWorker.register("/service-worker.js");
      console.log("SW registered");
    } catch (e) {
      console.warn("SW registration failed:", e);
    }
  }

  // Init auth
  await AUTH.init();

  // Show/hide nav based on auth
  const nav = document.querySelector(".app-nav");
  if (nav) {
    const authConfig = await AUTH.getConfig();
    const stytchConfigured = authConfig && authConfig.stytch_configured;
    nav.style.display = stytchConfigured && !AUTH.isAuthenticated() ? "none" : "flex";
  }

  // Init push notifications
  try { await NOTIFICATIONS.init(); } catch (e) { /* noop */ }

  // Render current route
  await Router.resolve();
});