// Historiador Login Page
const LoginPage = {
  async render() {
    const main = document.getElementById("app");
    const authConfig = await AUTH.getConfig();
    const configured = authConfig && authConfig.stytch_configured;

    main.innerHTML = `
      <div class="login-container">
        <div class="login-card">
          <div class="login-logo">
            <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
              <rect width="48" height="48" rx="12" fill="#0f3460"/>
              <text x="24" y="32" text-anchor="middle" fill="#e94560" font-size="24" font-weight="bold">H</text>
            </svg>
          </div>
          <h2>Welcome to Historiador</h2>
          <p class="login-subtitle">Multi-Agent History Generation System</p>

          ${configured ? `
            <div id="stytch-container" class="stytch-container"></div>
            <p class="login-hint">Sign in with your email — we'll send you a magic link</p>
          ` : `
            <div class="login-dev-mode">
              <p>Running in development mode (no authentication configured)</p>
              <button onclick="Router.navigate('new')" class="btn btn-primary">
                Continue to App →
              </button>
              <p class="login-hint">Set STYTCH_PROJECT_ID and STYTCH_SECRET in your .env for production</p>
            </div>
          `}

          <div class="login-footer">
            ${AUTH.isAuthenticated() ? `<p>Logged in as <strong>${AUTH.getUser()?.name || AUTH.getUser()?.email || AUTH.getUser()?.user_id}</strong></p>` : ""}
            ${AUTH.isAuthenticated() ? `<button onclick="AUTH.logout()" class="btn btn-secondary">Sign Out</button>` : ""}
          </div>
        </div>
      </div>
    `;

    // Initialize Stytch JS SDK if configured
    if (configured && authConfig.stytch_public_token && typeof stytch !== "undefined") {
      try {
        const sdk = stytch.init({
          project_id: authConfig.stytch_project_id,
          public_token: authConfig.stytch_public_token,
          environment: authConfig.stytch_environment || "test",
        });
        sdk.mount({
          element: "#stytch-container",
          products: ["emailMagicLinks"],
          emailMagicLinksOptions: {
            loginRedirectURL: window.location.origin + window.location.pathname + "#/new",
            signupRedirectURL: window.location.origin + window.location.pathname + "#/new",
            loginExpirationMinutes: 30,
          },
          otpOptions: {
            loginTemplateCode: "magic-link",
          },
          onSuccess: async (resp) => {
            if (resp.session_token) {
              try {
                await AUTH.loginWithSessionToken(resp.session_token);
                Router.navigate("new");
              } catch (e) {
                console.error("Login callback error:", e);
              }
            }
          },
          onError: (err) => {
            console.error("Stytch error:", err);
          },
        });
      } catch (e) {
        console.error("Stytch init error:", e);
      }
    }
  },
};