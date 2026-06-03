// Kanban Board Component
const Kanban = {
  lanes: [
    { id: "in_review", title: "In Review" },
    { id: "refining", title: "Refining" },
    { id: "accepted", title: "Accepted" },
    { id: "rejected", title: "Rejected" },
  ],

  async render(topicId = null) {
    const app = document.getElementById("app");
    app.innerHTML = `<h2 class="card-title">Kanban Board</h2><div class="kanban-lanes" id="kanban-lanes"></div>`;

    // Create lanes
    const lanesContainer = document.getElementById("kanban-lanes");
    const params = topicId ? `topic_id=${topicId}` : "";
    const data = await API.listHistories(params);
    const histories = data.histories || [];

    this.lanes.forEach((lane) => {
      const laneEl = document.createElement("div");
      laneEl.className = "kanban-lane";
      laneEl.innerHTML = `<div class="kanban-lane-title"><span class="badge badge-${lane.id}">${lane.title}</span></div>`;
      const cards = histories.filter((h) => h.status === lane.id);
      cards.forEach((h) => {
        const card = document.createElement("div");
        card.className = "kanban-card";
        card.innerHTML = `
          <div class="kanban-card-title">${h.title}</div>
          <div class="kanban-card-meta">${new Date(h.created_at).toLocaleDateString()} · ${h.feedback_count || 0} feedback</div>
        `;
        card.onclick = () => Router.navigate(`/history/${h.id}`);
        laneEl.appendChild(card);
      });
      if (cards.length === 0) {
        laneEl.innerHTML += `<div class="empty-state" style="padding:20px;font-size:0.85rem">No histories</div>`;
      }
      lanesContainer.appendChild(laneEl);
    });
  },
};