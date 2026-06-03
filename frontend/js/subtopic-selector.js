// Subtopic Selector
const SubtopicSelector = {
  async render(topicId) {
    const app = document.getElementById("app");
    app.innerHTML = `
      <div class="card" style="max-width:600px;margin:0 auto">
        <h2 class="card-title">Select Subtopics</h2>
        <p class="card-subtitle">Choose which subtopics to research and write about.</p>
        <div id="subtopic-list"></div>
        <div style="margin-top:16px;display:flex;gap:8px">
          <button id="btn-run-pipeline" class="btn btn-highlight" style="flex:1">Generate Histories →</button>
          <button id="btn-select-all" class="btn btn-outline">Select All</button>
        </div>
        <div id="pipeline-progress" style="display:none;margin-top:16px">
          <div class="spinner"></div>
          <p id="pipeline-status-text" style="text-align:center;color:var(--text-muted)">Researching...</p>
        </div>
      </div>
    `;

    const list = document.getElementById("subtopic-list");
    const topic = await API.getTopic(topicId);
    (topic.subtopics || []).forEach((sub) => {
      const item = document.createElement("div");
      item.className = "subtopic-item";
      item.innerHTML = `
        <input type="checkbox" class="subtopic-checkbox" data-id="${sub.id}" checked>
        <div class="subtopic-info">
          <div class="subtopic-title">${sub.title}</div>
          <div class="subtopic-desc">${sub.description || "No description"}</div>
        </div>
        <span class="badge badge-${sub.status}">${sub.status}</span>
      `;
      item.querySelector(".subtopic-checkbox").onchange = (e) => {
        API.updateSubtopic(topicId, sub.id, { status: e.target.checked ? "selected" : "todo" });
      };
      list.appendChild(item);
    });

    document.getElementById("btn-select-all").onclick = () => {
      document.querySelectorAll(".subtopic-checkbox").forEach((cb) => {
        cb.checked = true;
        API.updateSubtopic(topicId, cb.dataset.id, { status: "selected" });
      });
    };

    document.getElementById("btn-run-pipeline").onclick = async () => {
      const selected = [...document.querySelectorAll(".subtopic-checkbox:checked")].map((cb) => cb.dataset.id);
      if (selected.length === 0) return alert("Select at least one subtopic");
      const btn = document.getElementById("btn-run-pipeline");
      const progress = document.getElementById("pipeline-progress");
      const statusText = document.getElementById("pipeline-status-text");
      btn.disabled = true;
      progress.style.display = "block";
      try {
        await API.runPipeline({
          topic_title: topic.title,
          subtopic_ids: selected,
          profile_id: topic.profile_id || undefined,
        });
        statusText.textContent = "Done! Navigating to review...";
        setTimeout(() => Router.navigate(`/kanban/${topicId}`), 1000);
      } catch (e) {
        alert("Pipeline error: " + e.message);
        btn.disabled = false;
        progress.style.display = "none";
      }
    };
  },
};