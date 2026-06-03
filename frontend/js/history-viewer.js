// History Viewer
const HistoryViewer = {
  async render(historyId) {
    const app = document.getElementById("app");
    app.innerHTML = `<div id="history-content"><div class="spinner"></div></div>`;

    try {
      const history = await API.getHistory(historyId);
      app.innerHTML = `
        <div style="max-width:800px;margin:0 auto">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;flex-wrap:wrap;gap:8px">
            <h2 class="card-title" style="margin:0">${history.title}</h2>
            <span class="badge badge-${history.status}">${history.status.replace(/_/g, " ")}</span>
          </div>
          <div class="card history-content">${history.content}</div>
          <div class="card" style="margin-top:16px">
            <h3 class="card-title">Feedback</h3>
            <div style="display:flex;gap:8px;flex-wrap:wrap">
              <button id="feedback-accept" class="btn btn-success">&#10003; Accept</button>
              <button id="feedback-refine" class="btn btn-warning">&#9998; Request Refinement</button>
              <button id="feedback-reject" class="btn btn-danger">&#10007; Reject</button>
            </div>
            <div id="feedback-form" style="display:none;margin-top:12px">
              <textarea id="feedback-text" class="form-textarea" placeholder="Describe what needs to change..."></textarea>
              <button id="feedback-submit" class="btn btn-primary" style="margin-top:8px">Submit</button>
            </div>
          </div>
          <div style="margin-top:12px">
            <a href="#/kanban" class="btn btn-outline">&larr; Back to Kanban</a>
          </div>
        </div>
      `;

      document.getElementById("feedback-accept").onclick = async () => {
        await API.submitFeedback(historyId, "accept");
        Router.navigate(`/history/${historyId}`);
      };
      document.getElementById("feedback-reject").onclick = async () => {
        await API.submitFeedback(historyId, "reject");
        Router.navigate(`/history/${historyId}`);
      };
      document.getElementById("feedback-refine").onclick = () => {
        const f = document.getElementById("feedback-form");
        f.style.display = f.style.display === "none" ? "block" : "none";
      };
      document.getElementById("feedback-submit").onclick = async () => {
        const text = document.getElementById("feedback-text").value.trim();
        if (!text) return;
        await API.submitFeedback(historyId, "refine_request", text);
        Router.navigate(`/history/${historyId}`);
      };
    } catch (e) {
      app.innerHTML = `<div class="empty-state"><div class="empty-state-icon">&#9888;&#65039;</div><p>Error: ${e.message}</p></div>`;
    }
  },
};