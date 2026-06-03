// Topic Form Component
const TopicForm = {
  async render() {
    const app = document.getElementById("app");
    app.innerHTML = `
      <div class="card" style="max-width:600px;margin:40px auto">
        <h2 class="card-title">New Topic</h2>
        <div class="form-group">
          <label for="topic-title">What history do you want to explore?</label>
          <input type="text" id="topic-title" class="form-input" placeholder="e.g., The Silk Road, Viking Age, French Revolution...">
        </div>
        <div class="form-group">
          <label for="topic-profile">Writing Profile (optional)</label>
          <select id="topic-profile" class="form-select">
            <option value="">Default (neutral)</option>
          </select>
        </div>
        <button id="btn-create-topic" class="btn btn-highlight" style="width:100%">Start Scoping →</button>
        <div id="topic-progress" style="display:none;margin-top:16px">
          <div class="spinner"></div>
          <p style="text-align:center;color:var(--text-muted)">Creating topic...</p>
        </div>
      </div>
    `;

    // Load profiles
    try {
      const data = await API.listProfiles();
      const select = document.getElementById("topic-profile");
      (data.profiles || []).forEach((p) => {
        const opt = document.createElement("option");
        opt.value = p.id;
        opt.textContent = p.name;
        select.appendChild(opt);
      });
    } catch (e) { /* ignore */ }

    document.getElementById("btn-create-topic").onclick = async () => {
      const title = document.getElementById("topic-title").value.trim();
      if (!title) return;
      const btn = document.getElementById("btn-create-topic");
      const progress = document.getElementById("topic-progress");
      btn.disabled = true;
      progress.style.display = "block";
      try {
        const topic = await API.createTopic(title);
        Router.navigate(`/scoping/${topic.id}`);
      } catch (e) {
        alert("Error creating topic: " + e.message);
        btn.disabled = false;
        progress.style.display = "none";
      }
    };
  },
};