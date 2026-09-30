(function (root) {
  function providerAvailability(health) {
    const available = health.auth_mode === "supabase"
      ? Boolean(health.hosted_provider_available)
      : Boolean(health.provider_configured);
    return {
      available,
      label: available
        ? `${health.judgment_provider} · ${health.jev_model}`
        : "Hosted provider evaluation is currently unavailable.",
    };
  }

  function createManager(fetchImpl = fetch, createClient = () => root.supabase?.createClient) {
    let config = null;
    let client = null;
    let readyPromise = null;

    async function initialize() {
      const response = await fetchImpl("/api/v1/auth/config");
      if (!response.ok) throw new Error("Workspace configuration is unavailable.");
      config = await response.json();
      if (!config.enabled) return;
      const factory = createClient();
      if (!factory || !config.supabase_url || !config.publishable_key) {
        throw new Error("Guest sign-in is unavailable. Retry in a moment.");
      }
      client = factory(config.supabase_url, config.publishable_key, {
        auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: false },
      });
      const restored = await client.auth.getSession();
      if (restored.error) throw new Error("Guest session could not be restored.");
      if (!restored.data.session) {
        const created = await client.auth.signInAnonymously();
        if (created.error || !created.data.session) {
          throw new Error("Guest sign-in failed. Retry after checking the connection.");
        }
      }
    }

    function start() {
      if (!readyPromise) {
        readyPromise = initialize().catch((error) => {
          readyPromise = null;
          throw error;
        });
      }
      return readyPromise;
    }

    async function token() {
      await start();
      if (!config.enabled) return null;
      const { data, error } = await client.auth.getSession();
      if (error || !data.session?.access_token) {
        throw new Error("Guest session expired. Retry workspace sign-in.");
      }
      return data.session.access_token;
    }

    async function refresh() {
      const { data, error } = await client.auth.refreshSession();
      if (error || !data.session?.access_token) {
        throw new Error("Guest session expired. Retry workspace sign-in.");
      }
      return data.session.access_token;
    }

    async function request(path, options = {}) {
      await start();
      const headers = new Headers(options.headers || {});
      const accessToken = await token();
      if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
      let response = await fetchImpl(path, { ...options, headers });
      if (response.status === 401 && config.enabled) {
        headers.set("Authorization", `Bearer ${await refresh()}`);
        response = await fetchImpl(path, { ...options, headers });
      }
      let body;
      try {
        body = await response.json();
      } catch {
        body = null;
      }
      if (!response.ok) {
        const detail = body?.detail;
        const message =
          typeof detail === "string"
            ? detail
            : detail?.code === "hosted_provider_limit"
              ? "Free hosted evaluation limit reached for now. You can continue with deterministic checks or return later."
            : Array.isArray(detail)
              ? detail.map((error) => error.msg).join("; ")
              : `Request failed (${response.status})`;
        const error = new Error(message);
        error.status = response.status;
        throw error;
      }
      return body;
    }

    return { start, request, mode: () => config?.provider || null, providerAvailability };
  }

  const api = { createManager, providerAvailability };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.ClaimTrellisAuth = createManager();
})(typeof window !== "undefined" ? window : globalThis);
