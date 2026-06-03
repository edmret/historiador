// Scoping Chat Component
const ScopingChat = {
  topicId: null,

  async render(topicId) {
    this.topicId = topicId;
    const app = document.getElementById("app");
    app.innerHTML = `
      <div class="card" style="max-width:700px;margin:0 auto">
        <h2 class="card-title">Scoping Your Topic</h2>
        <div id="scoping-chat" class="chat-messages"></div>
        <div class="chat-input">
          <input type="text" id="scoping-input" class="form-input" placeholder="Type your answer..." disabled>
          <button id="scoping-send" class="btn btn-primary" disabled>Send</button>
        </div>
        <div id="scoping-loading" class="loading-overlay" style="display:none">
          <div class="spinner"></div>
          <p>Thinking...</p>
        </div>
      </div>
    `;

    // Load existing messages
    await this.loadMessages();
    document.getElementById("scoping-input").disabled = false;
    document.getElementById("scoping-send").disabled = false;

    const input = document.getElementById("scoping-input");
    const sendBtn = document.getElementById("scoping-send");

    const sendMsg = async () => {
      const text = input.value.trim();
      if (!text) return;
      input.value = "";
      input.disabled = true;
      sendBtn.disabled = true;
      document.getElementById("scoping-loading").style.display = "flex";
      this.addMessage("user", text);
      try {
        const result = await API.sendScopingMessage(this.topicId, text);
        if (result.complete) {
          this.addMessage("agent", "Scoping complete! Generating subtopics...");
          document.getElementById("scoping-loading").style.display = "none";
          // Navigate to subtopic selector
          setTimeout(() => Router.navigate(`/subtopics/${this.topicId}`), 1000);
          return;
        }
        this.addMessage("agent", result.agent_message);
      } catch (e) {
        this.addMessage("agent", "Error: " + e.message);
      }
      document.getElementById("scoping-loading").style.display = "none";
      input.disabled = false;
      sendBtn.disabled = false;
      input.focus();
    };

    sendBtn.onclick = sendMsg;
    input.onkeydown = (e) => { if (e.key === "Enter") sendMsg(); };
  },

  addMessage(role, content) {
    const container = document.getElementById("scoping-chat");
    const msg = document.createElement("div");
    msg.className = `chat-message ${role}`;
    msg.innerHTML = `<div class="role">${role}</div><div>${content}</div>`;
    container.appendChild(msg);
    container.scrollTop = container.scrollHeight;
  },

  async loadMessages() {
    try {
      const messages = await API.getScopingMessages(this.topicId);
      messages.forEach((m) => this.addMessage(m.role, m.content));
    } catch (e) { /* no messages yet */ }
  },
};