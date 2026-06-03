// Profile Manager
const ProfileManager = {
  async render() {
    const app = document.getElementById("app");
    app.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
        <h2 class="card-title" style="margin:0">Writing Profiles</h2>
        <button id="btn-new-profile" class="btn btn-primary">+ New Profile</button>
      </div>
      <div id="profile-list"></div>
    `;
    await this.loadProfiles();
    document.getElementById("btn-new-profile").onclick = () => this.showCreateForm();
  },

  async loadProfiles() {
    const container = document.getElementById("profile-list");
    try {
      const data = await API.listProfiles();
      const profiles = data.profiles || [];
      if (profiles.length === 0) {
        container.innerHTML = `<div class="empty-state"><div class="empty-state-icon">&#128221;</div><p>No profiles yet. Create one to define your writing style!</p></div>`;
        return;
      }
      container.innerHTML = profiles.map((p) => `
        <div class="card" data-id="${p.id}">
          <div style="display:flex;justify-content:space-between;align-items:start">
            <div>
              <div class="card-title">${p.name}</div>
              <div class="card-subtitle">${p.tone} &middot; ${p.audience} &middot; ${p.preferred_length}</div>
              ${p.description ? `<p style="color:var(--text-secondary);font-size:0.9rem">${p.description}</p>` : ""}
              ${p.style_notes ? `<p style="color:var(--text-muted);font-size:0.85rem">${p.style_notes}</p>` : ""}
            </div>
            <span class="badge badge-accepted">${p.tone}</span>
          </div>
        </div>
      `).join("");
    } catch (e) {
      container.innerHTML = `<div class="empty-state"><p>Error loading profiles: ${e.message}</p></div>`;
    }
  },

  showCreateForm() {
    const app = document.getElementById("app");
    app.innerHTML = `
      <div class="card" style="max-width:500px;margin:0 auto">
        <h2 class="card-title">Create Profile</h2>
        <div class="form-group">
          <label>Name</label>
          <input type="text" id="pf-name" class="form-input" placeholder="e.g., Epic Narrator">
        </div>
        <div class="form-group">
          <label>Description</label>
          <textarea id="pf-desc" class="form-textarea" placeholder="What makes this style unique?"></textarea>
        </div>
        <div class="form-group">
          <label>Tone</label>
          <select id="pf-tone" class="form-select">
            <option value="neutral">Neutral</option>
            <option value="dramatic">Dramatic</option>
            <option value="educational">Educational</option>
            <option value="humorous">Humorous</option>
            <option value="epic">Epic</option>
          </select>
        </div>
        <div class="form-group">
          <label>Audience</label>
          <select id="pf-audience" class="form-select">
            <option value="general">General</option>
            <option value="academic">Academic</option>
            <option value="young">Young</option>
            <option value="expert">Expert</option>
          </select>
        </div>
        <div class="form-group">
          <label>Length</label>
          <select id="pf-length" class="form-select">
            <option value="short">Short (~300 words)</option>
            <option value="medium" selected>Medium (~800 words)</option>
            <option value="long">Long (~1500 words)</option>
          </select>
        </div>
        <div class="form-group">
          <label>Style Notes</label>
          <textarea id="pf-style" class="form-textarea" placeholder="Any specific style preferences..."></textarea>
        </div>
        <div style="display:flex;gap:8px">
          <button id="pf-save" class="btn btn-highlight" style="flex:1">Save Profile</button>
          <button id="pf-cancel" class="btn btn-outline">Cancel</button>
        </div>
      </div>
    `;

    document.getElementById("pf-save").onclick = async () => {
      const data = {
        name: document.getElementById("pf-name").value,
        description: document.getElementById("pf-desc").value,
        tone: document.getElementById("pf-tone").value,
        audience: document.getElementById("pf-audience").value,
        preferred_length: document.getElementById("pf-length").value,
        style_notes: document.getElementById("pf-style").value,
      };
      if (!data.name) return alert("Name is required");
      try {
        await API.createProfile(data);
        Router.navigate("/profiles");
      } catch (e) {
        alert("Error: " + e.message);
      }
    };

    document.getElementById("pf-cancel").onclick = () => Router.navigate("/profiles");
  },
};