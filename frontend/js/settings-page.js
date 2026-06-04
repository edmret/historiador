// Historiador Settings Page
const SettingsPage = {
  activeTab: 'llm',

  CONFIG_KEYS: {
    // LLM
    llm_base_url: 'llm_base_url',
    llm_api_key: 'llm_api_key',
    llm_model: 'llm_model',
    scoping_model: 'scoping_model',
    research_model: 'research_model',
    compiler_model: 'compiler_model',
    writer_model: 'writer_model',
    editor_model: 'editor_model',
    profile_model: 'profile_model',
    // Search
    search_provider: 'search_provider',
    tavily_api_key: 'tavily_api_key',
    serpapi_api_key: 'serpapi_api_key',
    hermes_path: 'hermes_path',
    // Push
    vapid_public_key: 'vapid_public_key',
    vapid_private_key: 'vapid_private_key',
    vapid_claim_email: 'vapid_claim_email',
    // App
    default_num_histories: 'default_num_histories',
    default_num_research_agents: 'default_num_research_agents',
    max_scoping_rounds: 'max_scoping_rounds',
    max_queries_per_agent: 'max_queries_per_agent',
    max_pages_per_query: 'max_pages_per_query',
    max_chars_per_page: 'max_chars_per_page',
    max_research_tokens: 'max_research_tokens',
    research_timeout_seconds: 'research_timeout_seconds',
  },

  TAB_NAMES: ['llm', 'search', 'push', 'app'],

  configData: null,
  maskedKeys: [],

  async render() {
    const main = document.getElementById('app');
    main.innerHTML = this.getPageHTML();
    this.attachEventListeners();

    try {
      const resp = await API.request('GET', '/config');
      this.configData = resp.data || resp;
      this.maskedKeys = resp.masked_keys || [];
      this.populateForm();
    } catch (err) {
      this.showToast('Failed to load config: ' + err.message, 'error');
    }
  },

  getPageHTML() {
    return `
      <div class="settings-page">
        <h2 class="settings-title">Settings</h2>
        <div class="settings-tabs">
          <button class="settings-tab active" data-tab="llm">LLM</button>
          <button class="settings-tab" data-tab="search">Search</button>
          <button class="settings-tab" data-tab="push">Push</button>
          <button class="settings-tab" data-tab="app">App</button>
        </div>
        <div class="settings-content">
          ${this.getLLMTabHTML()}
          ${this.getSearchTabHTML()}
          ${this.getPushTabHTML()}
          ${this.getAppTabHTML()}
        </div>
        <div class="settings-actions">
          <button class="btn btn-primary" id="settings-save-btn">Save Settings</button>
          <button class="btn btn-highlight" id="settings-test-llm-btn" style="display:none;">Test LLM</button>
        </div>
        <div id="settings-status" class="settings-status"></div>
      </div>
    `;
  },

  getLLMTabHTML() {
    const agentModels = ['scoping', 'research', 'compiler', 'writer', 'editor', 'profile'];
    const agentLabels = {
      scoping: 'Scoping',
      research: 'Research',
      compiler: 'Compiler',
      writer: 'Writer',
      editor: 'Editor',
      profile: 'Profile',
    };

    const agentFields = agentModels.map(agent => `
      <div class="form-group">
        <label for="settings-${agent}_model">${agentLabels[agent]} Model</label>
        <input type="text" id="settings-${agent}_model" class="form-input"
               data-key="${agent}_model" placeholder="e.g. gpt-4o-mini">
      </div>
    `).join('');

    return `
      <div class="settings-tab-panel active" id="settings-panel-llm">
        <fieldset class="settings-fieldset">
          <legend>LLM Connection</legend>
          <div class="form-group">
            <label for="settings-llm_base_url">Base URL</label>
            <input type="text" id="settings-llm_base_url" class="form-input"
                   data-key="llm_base_url" placeholder="https://api.openai.com/v1">
          </div>
          <div class="form-group">
            <label for="settings-llm_api_key">API Key</label>
            <input type="password" id="settings-llm_api_key" class="form-input"
                   data-key="llm_api_key" placeholder="sk-...">
          </div>
          <div class="form-group">
            <label for="settings-llm_model">Global Model</label>
            <input type="text" id="settings-llm_model" class="form-input"
                   data-key="llm_model" placeholder="e.g. gpt-4o-mini">
          </div>
        </fieldset>
        <fieldset class="settings-fieldset">
          <legend>Per-Agent Models</legend>
          <p class="settings-hint">Override the global model for specific agents. Leave blank to use the global model.</p>
          ${agentFields}
        </fieldset>
      </div>
    `;
  },

  getSearchTabHTML() {
    return `
      <div class="settings-tab-panel" id="settings-panel-search">
        <fieldset class="settings-fieldset">
          <legend>Search Provider</legend>
          <div class="form-group">
            <label for="settings-search_provider">Provider</label>
            <select id="settings-search_provider" class="form-select" data-key="search_provider">
              <option value="duckduckgo">DuckDuckGo</option>
              <option value="direct">Direct</option>
              <option value="hermes">Hermes</option>
              <option value="tavily">Tavily</option>
              <option value="serpapi">SerpAPI</option>
              <option value="mock">Mock</option>
            </select>
          </div>
        </fieldset>
        <fieldset class="settings-fieldset">
          <legend>API Keys</legend>
          <div class="form-group">
            <label for="settings-tavily_api_key">Tavily API Key</label>
            <input type="password" id="settings-tavily_api_key" class="form-input"
                   data-key="tavily_api_key" placeholder="tvly-...">
          </div>
          <div class="form-group">
            <label for="settings-serpapi_api_key">SerpAPI API Key</label>
            <input type="password" id="settings-serpapi_api_key" class="form-input"
                   data-key="serpapi_api_key" placeholder="...">
          </div>
        </fieldset>
        <fieldset class="settings-fieldset">
          <legend>Hermes</legend>
          <div class="form-group">
            <label for="settings-hermes_path">Hermes Path</label>
            <input type="text" id="settings-hermes_path" class="form-input"
                   data-key="hermes_path" placeholder="/path/to/hermes">
          </div>
        </fieldset>
      </div>
    `;
  },

  getPushTabHTML() {
    return `
      <div class="settings-tab-panel" id="settings-panel-push">
        <fieldset class="settings-fieldset">
          <legend>VAPID Keys</legend>
          <p class="settings-hint">Voluntary Application Server Identification for Web Push notifications.</p>
          <div class="form-group">
            <label for="settings-vapid_public_key">VAPID Public Key</label>
            <input type="text" id="settings-vapid_public_key" class="form-input"
                   data-key="vapid_public_key" placeholder="BC...">
          </div>
          <div class="form-group">
            <label for="settings-vapid_private_key">VAPID Private Key</label>
            <input type="password" id="settings-vapid_private_key" class="form-input"
                   data-key="vapid_private_key" placeholder="...">
          </div>
          <div class="form-group">
            <label for="settings-vapid_claim_email">VAPID Claim Email</label>
            <input type="email" id="settings-vapid_claim_email" class="form-input"
                   data-key="vapid_claim_email" placeholder="admin@example.com">
          </div>
        </fieldset>
      </div>
    `;
  },

  getAppTabHTML() {
    return `
      <div class="settings-tab-panel" id="settings-panel-app">
        <fieldset class="settings-fieldset">
          <legend>Default Values</legend>
          <div class="form-group">
            <label for="settings-default_num_histories">Default Number of Histories</label>
            <input type="number" id="settings-default_num_histories" class="form-input"
                   data-key="default_num_histories" min="1" max="50">
          </div>
          <div class="form-group">
            <label for="settings-default_num_research_agents">Default Number of Research Agents</label>
            <input type="number" id="settings-default_num_research_agents" class="form-input"
                   data-key="default_num_research_agents" min="1" max="20">
          </div>
        </fieldset>
        <fieldset class="settings-fieldset">
          <legend>Scoping Limits</legend>
          <div class="form-group">
            <label for="settings-max_scoping_rounds">Max Scoping Rounds</label>
            <input type="number" id="settings-max_scoping_rounds" class="form-input"
                   data-key="max_scoping_rounds" min="1" max="50">
          </div>
        </fieldset>
        <fieldset class="settings-fieldset">
          <legend>Research Limits</legend>
          <div class="form-group">
            <label for="settings-max_queries_per_agent">Max Queries Per Agent</label>
            <input type="number" id="settings-max_queries_per_agent" class="form-input"
                   data-key="max_queries_per_agent" min="1" max="100">
          </div>
          <div class="form-group">
            <label for="settings-max_pages_per_query">Max Pages Per Query</label>
            <input type="number" id="settings-max_pages_per_query" class="form-input"
                   data-key="max_pages_per_query" min="1" max="50">
          </div>
          <div class="form-group">
            <label for="settings-max_chars_per_page">Max Chars Per Page</label>
            <input type="number" id="settings-max_chars_per_page" class="form-input"
                   data-key="max_chars_per_page" min="100" max="100000">
          </div>
          <div class="form-group">
            <label for="settings-max_research_tokens">Max Research Tokens</label>
            <input type="number" id="settings-max_research_tokens" class="form-input"
                   data-key="max_research_tokens" min="100" max="1000000">
          </div>
          <div class="form-group">
            <label for="settings-research_timeout_seconds">Research Timeout (seconds)</label>
            <input type="number" id="settings-research_timeout_seconds" class="form-input"
                   data-key="research_timeout_seconds" min="10" max="600">
          </div>
        </fieldset>
      </div>
    `;
  },

  attachEventListeners() {
    // Tab switching
    document.querySelectorAll('.settings-tab').forEach(tab => {
      tab.addEventListener('click', () => this.switchTab(tab.dataset.tab));
    });

    // Save
    document.getElementById('settings-save-btn').addEventListener('click', () => this.saveConfig());

    // Test LLM
    document.getElementById('settings-test-llm-btn').addEventListener('click', () => this.testLLM());
  },

  switchTab(tabName) {
    this.activeTab = tabName;

    // Update tab buttons
    document.querySelectorAll('.settings-tab').forEach(tab => {
      tab.classList.toggle('active', tab.dataset.tab === tabName);
    });

    // Update panels
    document.querySelectorAll('.settings-tab-panel').forEach(panel => {
      panel.classList.toggle('active', panel.id === `settings-panel-${tabName}`);
    });

    // Show/hide Test LLM button
    const testBtn = document.getElementById('settings-test-llm-btn');
    testBtn.style.display = tabName === 'llm' ? '' : 'none';
  },

  getValue(key) {
    const el = document.querySelector(`[data-key="${key}"]`);
    if (!el) return null;
    if (el.type === 'number') {
      const val = parseFloat(el.value);
      return isNaN(val) ? null : val;
    }
    return el.value;
  },

  setValue(key, value) {
    const el = document.querySelector(`[data-key="${key}"]`);
    if (!el) return;
    if (value === null || value === undefined) {
      el.value = '';
      return;
    }
    el.value = value;
  },

  populateForm() {
    if (!this.configData) return;

    for (const [field, configKey] of Object.entries(this.CONFIG_KEYS)) {
      const value = this.configData[configKey];
      this.setValue(field, value);
    }

    // Pre-populate per-agent model dropdowns with global model as placeholder
    const globalModel = this.configData.llm_model || '';
    ['scoping_model', 'research_model', 'compiler_model', 'writer_model', 'editor_model', 'profile_model'].forEach(key => {
      const el = document.querySelector(`[data-key="${key}"]`);
      if (el && !el.value) {
        el.placeholder = globalModel || 'inherit from global model';
      }
    });
  },

  async saveConfig() {
    const saveBtn = document.getElementById('settings-save-btn');
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving...';

    const payload = {};
    for (const [field, configKey] of Object.entries(this.CONFIG_KEYS)) {
      const value = this.getValue(field);
      if (value !== null && value !== '') {
        payload[configKey] = value;
      } else {
        // For per-agent models, send null to clear override (inherit global)
        if (configKey.endsWith('_model') && configKey !== 'llm_model') {
          payload[configKey] = null;
        }
      }
    }

    try {
      const resp = await API.request('PUT', '/config', payload);
      this.configData = resp.data || resp;
      this.showToast('Settings saved successfully!', 'success');
    } catch (err) {
      this.showToast('Failed to save settings: ' + err.message, 'error');
    } finally {
      saveBtn.disabled = false;
      saveBtn.textContent = 'Save Settings';
    }
  },

  async testLLM() {
    const testBtn = document.getElementById('settings-test-llm-btn');
    testBtn.disabled = true;
    testBtn.textContent = 'Testing...';

    const statusDiv = document.getElementById('settings-status');
    statusDiv.className = 'settings-status';
    statusDiv.textContent = 'Testing LLM connection...';

    const base_url = this.getValue('llm_base_url');
    const api_key = this.getValue('llm_api_key');
    const model = this.getValue('llm_model');

    if (!base_url || !model) {
      statusDiv.className = 'settings-status settings-status-error';
      statusDiv.textContent = 'Base URL and Model are required for testing.';
      testBtn.disabled = false;
      testBtn.textContent = 'Test LLM';
      return;
    }

    try {
      const resp = await API.request('POST', '/config/test-llm', { base_url, api_key, model });
      if (resp.success) {
        statusDiv.className = 'settings-status settings-status-success';
        statusDiv.textContent = resp.message || 'LLM connection successful!';
      } else {
        statusDiv.className = 'settings-status settings-status-error';
        statusDiv.textContent = resp.message || 'LLM test failed.';
      }
    } catch (err) {
      statusDiv.className = 'settings-status settings-status-error';
      statusDiv.textContent = 'Error testing LLM: ' + err.message;
    } finally {
      testBtn.disabled = false;
      testBtn.textContent = 'Test LLM';
    }
  },

  showToast(message, type) {
    // Remove existing toasts
    document.querySelectorAll('.toast').forEach(t => t.remove());

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transition = 'opacity 0.3s';
      setTimeout(() => toast.remove(), 300);
    }, 3000);
  },
};