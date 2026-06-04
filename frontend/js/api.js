// Historiador API Client
const API = {
  BASE: "/api",

  async request(method, path, body = null) {
    const opts = {
      method,
      headers: { "Content-Type": "application/json" },
    };
    // Inject auth token if available
    const token = AUTH.getToken();
    if (token) {
      opts.headers["Authorization"] = `Bearer ${token}`;
    }
    if (body) opts.body = JSON.stringify(body);
    const resp = await fetch(this.BASE + path, opts);
    if (resp.status === 401) {
      // Session expired — redirect to login
      AUTH.logout();
      window.location.hash = "#/login";
      throw new Error("Session expired");
    }
    if (!resp.ok) {
      const err = await resp.text();
      throw new Error(`API ${method} ${path}: ${resp.status} — ${err}`);
    }
    if (resp.status === 204) return null;
    return resp.json();
  },

  // Topics
  listTopics: () => API.request("GET", "/topics"),
  createTopic: (title) => API.request("POST", "/topics", { title }),
  getTopic: (id) => API.request("GET", `/topics/${id}`),

  // Scoping
  getScopingMessages: (topicId) => API.request("GET", `/topics/${topicId}/scoping`),
  sendScopingMessage: (topicId, content) => API.request("POST", `/topics/${topicId}/scoping`, { content }),
  updateSubtopic: (topicId, subId, data) => API.request("PATCH", `/topics/${topicId}/subtopics/${subId}`, data),

  // Profiles
  listProfiles: () => API.request("GET", "/profiles"),
  createProfile: (data) => API.request("POST", "/profiles", data),
  getProfile: (id) => API.request("GET", `/profiles/${id}`),
  updateProfile: (id, data) => API.request("PATCH", `/profiles/${id}`, data),

  // Histories
  listHistories: (params = {}) => {
    const qs = new URLSearchParams(params).toString();
    return API.request("GET", `/histories${qs ? "?" + qs : ""}`);
  },
  getHistory: (id) => API.request("GET", `/histories/${id}`),
  submitFeedback: (historyId, feedbackType, feedbackText = null) =>
    API.request("POST", `/histories/${historyId}/feedback`, { feedback_type: feedbackType, feedback_text: feedbackText }),

  // Pipeline
  runPipeline: (data) => API.request("POST", "/pipeline/run", data),
  getPipelineStatus: (topicId) => API.request("GET", `/pipeline/status/${topicId}`),

  // Notifications
  subscribePush: (sub) => API.request("POST", "/notifications/subscribe", sub),
  unsubscribePush: (sub) => API.request("POST", "/notifications/unsubscribe", sub),

  // Config
  getConfig: () => API.request("GET", "/config"),
  updateConfig: (data) => API.request("PUT", "/config", data),
  testLLM: (data) => API.request("POST", "/config/test-llm", data),

  // Auth
  login: (sessionToken) => API.request("POST", "/auth/login", { session_token: sessionToken }),
  getMe: () => {
    const token = AUTH.getToken();
    const headers = { "Content-Type": "application/json" };
    if (token) headers["Authorization"] = `Bearer ${token}`;
    return fetch("/api/auth/me", { headers }).then((r) => (r.ok ? r.json() : null));
  },
  createApiToken: (label) => API.request("POST", "/auth/tokens", { label }),
  listApiTokens: () => API.request("GET", "/auth/tokens"),
  revokeApiToken: (id) => API.request("DELETE", `/auth/tokens/${id}`),
};