(function (root) {
  const CONFLICT_COPY = "This sign-in method already belongs to another ClaimTrellis account. Your current guest workspace will not be merged automatically.";
  const LINK_KEY = "claimtrellis-link-user-id";
  const IDENTITY_COPY = "Your account session changed. Reload before continuing; no audit ownership was changed.";
  const isConflict = (error) => ["email_exists", "identity_already_exists", "user_already_exists"].includes(error?.code);

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
    let status = { kind: "unknown", userId: null, email: null };
    let pendingEmail = null;
    let linkingUserId = null;
    let signOutPromise = null;
    let subscription = null;
    const listeners = new Set();
    const linkStorage = root.sessionStorage;

    function setState(kind, user = null, notice = null) {
      const next = { kind, userId: user?.id || null, email: user?.email || null, notice };
      if (JSON.stringify(next) === JSON.stringify(status)) return currentState();
      status = next;
      listeners.forEach((listener) => listener({ ...status }));
      return { ...status };
    }
    function currentState() { return { ...status }; }
    function onAuthStateChange(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    }
    async function verifiedUser(fallback) {
      if (!client.auth.getUser) return fallback;
      const result = await client.auth.getUser();
      if (result.error || !result.data?.user) throw new Error("Account session could not be verified.");
      return result.data.user;
    }
    function applyUser(user) {
      if (status.kind === "error") return currentState();
      const expected = linkingUserId || linkStorage?.getItem(LINK_KEY)
        || (["guest", "linking"].includes(status.kind) ? status.userId : null);
      if (user && expected && user.id !== expected) {
        return setState("error", null, IDENTITY_COPY);
      }
      if (!user) return setState("signed_out");
      const permanent = user.is_anonymous === false;
      if (permanent) {
        linkingUserId = null;
        linkStorage?.removeItem(LINK_KEY);
      }
      return setState(permanent ? "permanent" : linkingUserId ? "linking" : "guest", user);
    }
    async function refreshIdentity() {
      await start();
      if (status.kind === "error") throw new Error(IDENTITY_COPY);
      const restored = await client.auth.getSession();
      if (restored.error) throw new Error("Session could not be restored.");
      const user = restored.data.session ? await verifiedUser(restored.data.session.user) : null;
      applyUser(user);
      if (status.kind === "error") throw new Error(IDENTITY_COPY);
      return currentState();
    }
    async function initialize() {
      const response = await fetchImpl("/api/v1/auth/config");
      if (!response.ok) throw new Error("Workspace configuration is unavailable.");
      config = await response.json();
      if (!config.enabled) return setState("guest");
      const factory = createClient();
      if (!factory || !config.supabase_url || !config.publishable_key) {
        throw new Error("Account sign-in is unavailable. Retry in a moment.");
      }
      const callbackParams = new URLSearchParams(root.location?.hash?.slice(1));
      const callbackError = callbackParams.get("error_code") || callbackParams.get("error");
      if (callbackError && root.history?.replaceState) {
        for (const key of ["error", "error_code", "error_description"]) callbackParams.delete(key);
        root.history.replaceState(null, "", root.location.pathname + root.location.search
          + (callbackParams.size ? `#${callbackParams}` : ""));
      }
      client = factory(config.supabase_url, config.publishable_key, {
        auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
      });
      // Supabase callbacks must stay synchronous: do not call getUser/getSession inside them.
      subscription?.unsubscribe();
      subscription = client.auth.onAuthStateChange?.((event, session) => {
        if (event !== "INITIAL_SESSION") applyUser(session?.user);
      })?.data?.subscription;
      const restored = await client.auth.getSession();
      if (restored.error) throw new Error("Session could not be restored.");
      if (!restored.data.session) {
        if (linkStorage?.getItem(LINK_KEY)) {
          setState("error");
          throw new Error(CONFLICT_COPY);
        }
        return setState("signed_out", null, callbackError ? "Google sign-in was not completed. Please try again." : null);
      }
      const user = await verifiedUser(restored.data.session.user);
      const expected = linkStorage?.getItem(LINK_KEY);
      if (expected) {
        if (user?.id !== expected) {
          setState("error");
          throw new Error(CONFLICT_COPY);
        }
        if (user?.is_anonymous === false) linkStorage.removeItem(LINK_KEY);
      }
      const notice = callbackError
        ? isConflict({ code: callbackError }) ? CONFLICT_COPY : "Google sign-in was not completed. Please try again."
        : expected && user?.is_anonymous !== false ? "Google linking was not completed. Your guest workspace is still available." : null;
      if (expected && user?.id === expected && user?.is_anonymous !== false) linkStorage.removeItem(LINK_KEY);
      return setState(user?.is_anonymous === false ? "permanent" : "guest", user, notice);
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
    function requireAccount() {
      if (!config?.enabled || !config.account_access_enabled) {
        throw new Error("Account access is not enabled yet.");
      }
    }
    async function continueAsGuest() {
      await start();
      if (!config.enabled) return currentState();
      if (status.kind === "error") throw new Error("Account identity changed unexpectedly. Do not create a new guest workspace.");
      if (["guest", "linking", "permanent"].includes(status.kind)) return currentState();
      const created = await client.auth.signInAnonymously();
      if (created.error || !created.data?.session) {
        throw new Error("Guest sign-in failed. Retry after checking the connection.");
      }
      return setState("guest", created.data.user || created.data.session.user);
    }
    async function sendEmailOtp(email) {
      await start();
      requireAccount();
      if (status.kind !== "signed_out") throw new Error("Use Save workspace to link this guest account.");
      const result = await client.auth.signInWithOtp({ email });
      if (result.error) throw new Error("Could not send the sign-in code. Please retry.");
      pendingEmail = email;
      linkingUserId = null;
    }
    async function linkGuestEmail(email) {
      await start();
      requireAccount();
      if (status.kind !== "guest" || !status.userId) throw new Error("Open a guest workspace first.");
      const originId = status.userId;
      const result = await client.auth.updateUser({ email });
      if (result.error) throw new Error(isConflict(result.error) ? CONFLICT_COPY : "Could not send the linking code. Your guest workspace is still available. Please retry.");
      pendingEmail = email;
      linkingUserId = originId;
      setState("linking", { id: originId });
    }
    async function verifyEmailOtp(code) {
      await start();
      requireAccount();
      if (!pendingEmail || !/^\d{6}$/.test(code)) throw new Error("Enter the 6-digit code.");
      const previousId = linkingUserId;
      const result = await client.auth.verifyOtp({
        email: pendingEmail, token: code, type: previousId ? "email_change" : "email",
      });
      if (result.error) throw new Error("The code is invalid or expired. Request another code.");
      const user = await verifiedUser(result.data?.user);
      if (previousId && user?.id !== previousId) {
        setState("error");
        throw new Error(CONFLICT_COPY);
      }
      if (!user || user.is_anonymous !== false) throw new Error("Account verification is incomplete.");
      pendingEmail = null;
      linkingUserId = null;
      setState("permanent", user);
      await request("/api/v1/account/sync", { method: "POST" });
      return currentState();
    }
    async function signInWithGoogle() {
      await start();
      requireAccount();
      if (status.kind !== "signed_out") throw new Error("Use Save workspace to link this guest account.");
      const result = await client.auth.signInWithOAuth({
        provider: "google", options: { redirectTo: root.location?.origin || undefined },
      });
      if (result.error) throw new Error("Google sign-in could not start.");
    }
    async function linkGuestGoogle() {
      await start();
      requireAccount();
      if (status.kind !== "guest" || !status.userId) throw new Error("Open a guest workspace first.");
      const originId = status.userId;
      linkStorage?.setItem(LINK_KEY, originId);
      const result = await client.auth.linkIdentity({
        provider: "google", options: { redirectTo: root.location?.origin || undefined },
      });
      if (result.error) {
        linkStorage?.removeItem(LINK_KEY);
        throw new Error(isConflict(result.error) ? CONFLICT_COPY : "Google linking could not start. Your guest workspace is still available. Please retry.");
      }
      setState("linking", { id: originId });
    }
    function signOut() {
      if (signOutPromise) return signOutPromise;
      signOutPromise = (async () => {
        // A linked account or another tab may have changed the actual session since render.
        await refreshIdentity();
        if (status.kind === "signed_out") return;
        if (status.kind !== "permanent") throw new Error("Save your guest workspace before signing out.");
        const result = await client.auth.signOut();
        if (result.error) throw new Error("Could not sign out. Please retry.");
        pendingEmail = null;
        linkingUserId = null;
        linkStorage?.removeItem(LINK_KEY);
        setState("signed_out");
      })().finally(() => { signOutPromise = null; });
      return signOutPromise;
    }
    function keepGuestWorkspace() {
      if (status.kind !== "guest" && status.kind !== "linking") return currentState();
      const userId = linkingUserId || status.userId;
      pendingEmail = null;
      linkingUserId = null;
      linkStorage?.removeItem(LINK_KEY);
      return setState("guest", { id: userId });
    }
    async function switchToExistingAccount() {
      await start();
      if (status.kind !== "guest" && status.kind !== "linking") {
        throw new Error("No guest workspace is active.");
      }
      const result = await client.auth.signOut();
      if (result.error) throw new Error("Could not switch accounts. Your guest workspace remains open.");
      pendingEmail = null;
      linkingUserId = null;
      linkStorage?.removeItem(LINK_KEY);
      setState("signed_out");
    }
    async function getAccessToken() {
      await start();
      if (status.kind === "error") throw new Error(IDENTITY_COPY);
      if (!config.enabled) return null;
      const { data, error } = await client.auth.getSession();
      if (error || !data.session?.access_token) {
        setState("signed_out");
        throw new Error("Choose Continue as guest or Sign in to open a workspace.");
      }
      if (status.userId && data.session.user?.id && data.session.user.id !== status.userId) {
        setState("error", null, IDENTITY_COPY);
        throw new Error(IDENTITY_COPY);
      }
      return data.session.access_token;
    }
    async function request(path, options = {}) {
      await start();
      const headers = new Headers(options.headers || {});
      const accessToken = await getAccessToken();
      const owner = status.userId;
      if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
      let response = await fetchImpl(path, { ...options, headers });
      if (response.status === 401 && config.enabled) {
        const refreshed = await client.auth.refreshSession();
        if (refreshed.error || !refreshed.data.session?.access_token) {
          throw new Error("Session expired. Sign in again.");
        }
        if (status.kind === "error" || status.userId !== owner
          || (owner && refreshed.data.session.user?.id && refreshed.data.session.user.id !== owner)) {
          throw new Error(IDENTITY_COPY);
        }
        headers.set("Authorization", `Bearer ${refreshed.data.session.access_token}`);
        response = await fetchImpl(path, { ...options, headers });
      }
      let body;
      try { body = await response.json(); } catch { body = null; }
      if (status.kind === "error" || status.userId !== owner) throw new Error(IDENTITY_COPY);
      if (!response.ok) {
        const detail = body?.detail;
        const message = typeof detail === "string" ? detail
          : detail?.code === "hosted_provider_limit"
            ? "Free hosted evaluation limit reached for now. You can continue with deterministic checks or return later."
            : Array.isArray(detail) ? detail.map((error) => error.msg).join("; ")
              : `Request failed (${response.status})`;
        const error = new Error(message);
        error.status = response.status;
        throw error;
      }
      return body;
    }
    return {
      start, currentState, onAuthStateChange, continueAsGuest,
      sendEmailOtp, verifyEmailOtp, linkGuestEmail, signInWithGoogle, linkGuestGoogle,
      signOut, keepGuestWorkspace, switchToExistingAccount, getAccessToken,
      request, mode: () => config?.provider || null,
      accountEnabled: () => Boolean(config?.account_access_enabled), providerAvailability,
    };
  }
  const api = { createManager, providerAvailability, CONFLICT_COPY };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.ClaimTrellisAuth = createManager();
})(typeof window !== "undefined" ? window : globalThis);
