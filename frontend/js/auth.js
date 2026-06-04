// Historiador Authentication Module (Stytch)
const AUTH = {
  STORAGE_KEY: "historiador_session",
  _sessionToken: null,
  _user: null,

  // ── Init ─────────────────────────────────────────────────────────

  async init() {
    // Restore session from local storage
    const saved = localStorage.getItem(this.STORAGE_KEY);
    if (saved) {
      try {
        const data = JSON.parse(saved);
        this._sessionToken = data.token;
        this._user = data.user;
      } catch {
        // Corrupted storage, clear it
        localStorage.removeItem(this.STORAGE_KEY);
      }
    }

    // Check if we have a Stytch magic link callback
    const stytchToken = this._getStytchTokenFromUrl();
    if (stytchToken) {
      // Remove the token from URL without reloading
      window.history.replaceState({}, document.title, window.location.pathname + window.location.hash);
      await this._handleStytchCallback(stytchToken);
    }
  },

  // ── Public config ─────────────────────────────────────────────────

  async getConfig() {
    try {
      const resp = await fetch("/api/auth/config");
      return await resp.json();
    } catch {
      return null;
    }
  },

  // ── Login ─────────────────────────────────────────────────────────

  async loginWithMagicLink(email) {
    // Delegate to Stytch — the SDK will handle the email send
    // This is called by the Stytch UI component
    console.log("Sending magic link to", email);
  },

  async loginWithSessionToken(sessionToken) {
    const resp = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_token: sessionToken }),
    });
    if (!resp.ok) throw new Error("Login failed");
    const user = await resp.json();
    this._sessionToken = sessionToken;
    this._user = user;
    localStorage.setItem(
      this.STORAGE_KEY,
      JSON.stringify({ token: sessionToken, user })
    );
    return user;
  },

  // ── Session check ─────────────────────────────────────────────────

  async getMe() {
    if (!this._sessionToken) return null;
    try {
      const resp = await fetch("/api/auth/me", {
        headers: { Authorization: `Bearer ${this._sessionToken}` },
      });
      if (!resp.ok) {
        this.logout();
        return null;
      }
      return await resp.json();
    } catch {
      return null;
    }
  },

  // ── Logout ────────────────────────────────────────────────────────

  logout() {
    this._sessionToken = null;
    this._user = null;
    localStorage.removeItem(this.STORAGE_KEY);
    window.location.hash = "#/login";
  },

  // ── Token accessor for API client ─────────────────────────────────

  getToken() {
    return this._sessionToken;
  },

  isAuthenticated() {
    return !!this._sessionToken || !!this._user;
  },

  getUser() {
    return this._user;
  },

  // ── Internal ──────────────────────────────────────────────────────

  _getStytchTokenFromUrl() {
    // Stytch magic links append &stytch_token_type=...&token=...
    const params = new URLSearchParams(window.location.search);
    const tokenType = params.get("stytch_token_type");
    const token = params.get("token");
    if (!token || !tokenType) return null;
    return { token, token_type: tokenType };
  },

  async _handleStytchCallback({ token, token_type }) {
    // Exchange the magic link token for a session via Stytch SDK
    // This requires the Stytch JS SDK to be loaded
    if (typeof stytch !== "undefined") {
      try {
        const resp = await stytch.authenticate({
          token,
          token_type,
        });
        if (resp.session_token) {
          await this.loginWithSessionToken(resp.session_token);
          // Navigate to default page
          window.location.hash = "#/new";
        }
      } catch (err) {
        console.error("Stytch callback error:", err);
      }
    } else {
      // Fallback: send the token to the backend for server-side exchange
      await this.loginWithSessionToken(token);
    }
  },
};
