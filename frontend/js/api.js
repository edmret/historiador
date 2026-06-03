// Historiador API Client
const API = {
  BASE: "/api",

  async request(method, path, body = null) {
    const opts = {
      method,
      headers: { "Content-Type": "application/json" },
    };
    if (body) opts.body = JSON.stringify(body);
    const resp = await fetch(this.BASE + path, opts);
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
};