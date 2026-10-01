const assert = require("node:assert/strict");
const { test } = require("node:test");
const { createManager, providerAvailability } = require("./auth.js");

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
const config = {
  enabled: true,
  provider: "supabase",
  supabase_url: "https://example.supabase.co",
  publishable_key: "sb_publishable_test",
  account_access_enabled: true,
};

test("hosted provider is visibly unavailable while the feature flag is off", () => {
  assert.deepEqual(providerAvailability({
    auth_mode: "supabase", provider_configured: true,
    hosted_provider_enabled: false, hosted_provider_available: false,
    judgment_provider: "typesafe_jev", jev_model: "jev-1.13.0",
  }), {
    available: false,
    label: "Hosted provider evaluation is currently unavailable.",
  });
});

test("structured hosted 429 receives safe deterministic fallback copy", async () => {
  const manager = createManager(async (path) => {
    if (path === "/api/v1/auth/config") return json({ enabled: false, provider: "local" });
    return json({ detail: {
      code: "hosted_provider_limit", scope: "ip", message: "Hosted provider usage limit reached."
    } }, 429);
  });
  await assert.rejects(
    manager.request("/api/v1/audits"),
    /Free hosted evaluation limit reached for now. You can continue with deterministic checks/,
  );
});

test("first visit creates no user; Guest choice creates one before protected history", async () => {
  const paths = [];
  let signIns = 0;
  let session = null;
  const client = {
    auth: {
      getSession: async () => ({ data: { session }, error: null }),
      signInAnonymously: async () => {
        signIns++;
        session = { access_token: "guest-token", user: { id: "guest-1", is_anonymous: true } };
        return { data: { session }, error: null };
      },
    },
  };
  const manager = createManager(
    async (path, options) => {
      paths.push(path);
      if (path === "/api/v1/auth/config") return json(config);
      assert.equal(options.headers.get("Authorization"), "Bearer guest-token");
      return json([]);
    },
    () => () => client,
  );
  await manager.start();
  assert.equal(manager.currentState().kind, "signed_out");
  assert.equal(signIns, 0);
  await assert.rejects(manager.request("/api/v1/audits?limit=10"), /Choose Continue as guest/);
  await manager.continueAsGuest();
  await manager.continueAsGuest();
  await manager.request("/api/v1/audits?limit=10");
  assert.equal(signIns, 1);
  assert.deepEqual(paths, ["/api/v1/auth/config", "/api/v1/audits?limit=10"]);
});

test("restored guest session does not create a new user", async () => {
  const client = {
    auth: {
      getSession: async () => ({ data: { session: { access_token: "restored" } } }),
      signInAnonymously: () => assert.fail("unexpected new user"),
    },
  };
  const manager = createManager(
    async (path, options) => path === "/api/v1/auth/config"
      ? json(config)
      : (assert.equal(options.headers.get("Authorization"), "Bearer restored"), json([])),
    () => () => client,
  );
  await manager.request("/api/v1/audits");
});

test("one 401 refreshes and retries exactly once", async () => {
  let calls = 0;
  let refreshed = 0;
  const client = {
    auth: {
      getSession: async () => ({ data: { session: { access_token: "old" } } }),
      refreshSession: async () => {
        refreshed++;
        return { data: { session: { access_token: "new" } } };
      },
    },
  };
  const manager = createManager(
    async (path, options) => {
      if (path === "/api/v1/auth/config") return json(config);
      calls++;
      assert.equal(options.headers.get("Authorization"), calls === 1 ? "Bearer old" : "Bearer new");
      return json(calls === 1 ? { detail: "Invalid session." } : [], calls === 1 ? 401 : 200);
    },
    () => () => client,
  );
  await manager.request("/api/v1/audits");
  assert.equal(calls, 2);
  assert.equal(refreshed, 1);
});

test("FormData remains unmodified and local mode sends no bearer header", async () => {
  const data = new FormData();
  data.append("document", new Blob(["source text"]), "source.txt");
  const manager = createManager(async (path, options) => {
    if (path === "/api/v1/auth/config") return json({ enabled: false, provider: "local" });
    assert.equal(options.body, data);
    assert.equal(options.headers.has("Content-Type"), false);
    assert.equal(options.headers.has("Authorization"), false);
    return json({ text: "source text" });
  });
  await manager.request("/api/v1/documents/parse", { method: "POST", body: data });
});

test("protected requests wait for auth readiness and failure never falls back to local", async () => {
  let resolveConfig;
  const configReady = new Promise((resolve) => { resolveConfig = resolve; });
  let protectedCalls = 0;
  const manager = createManager(async (path) => {
    if (path === "/api/v1/auth/config") return configReady;
    protectedCalls++;
    return json([]);
  }, () => undefined);
  const pending = manager.request("/api/v1/audits");
  await Promise.resolve();
  assert.equal(protectedCalls, 0);
  resolveConfig(json(config));
  await assert.rejects(pending, /Account sign-in is unavailable/);
  assert.equal(protectedCalls, 0);
});

test("direct Email OTP verifies six digits and syncs a permanent profile", async () => {
  const calls = [];
  let session = null;
  const user = { id: "permanent-1", email: "reader@example.com", is_anonymous: false };
  const client = { auth: {
    getSession: async () => ({ data: { session } }),
    signInWithOtp: async (input) => (calls.push(input), { error: null }),
    verifyOtp: async (input) => {
      calls.push(input);
      session = { access_token: "otp-token", user };
      return { data: { user } };
    },
    getUser: async () => ({ data: { user } }),
  } };
  const manager = createManager(async (path, options) => {
    if (path === "/api/v1/auth/config") return json(config);
    assert.equal(path, "/api/v1/account/sync");
    assert.equal(options.headers.get("Authorization"), "Bearer otp-token");
    calls.push("sync");
    return json({ user_id: user.id });
  }, () => () => client);
  await manager.sendEmailOtp(user.email);
  await assert.rejects(manager.verifyEmailOtp("12345"), /6-digit/);
  await manager.verifyEmailOtp("123456");
  assert.equal(manager.currentState().kind, "permanent");
  assert.deepEqual(calls, [
    { email: user.email },
    { email: user.email, token: "123456", type: "email" },
    "sync",
  ]);
});

test("guest Email linking preserves exact user ID and existing audit ownership", async () => {
  const guestId = "guest-42";
  let user = { id: guestId, is_anonymous: true };
  let session = { access_token: "guest-token", user };
  const calls = [];
  const client = { auth: {
    getSession: async () => ({ data: { session } }),
    getUser: async () => ({ data: { user } }),
    updateUser: async (input) => (calls.push(input), { data: { user } }),
    verifyOtp: async (input) => {
      calls.push(input);
      user = { id: guestId, email: "reader@example.com", is_anonymous: false };
      session = { access_token: "linked-token", user };
      return { data: { user } };
    },
  } };
  const manager = createManager(async (path, options) => {
    if (path === "/api/v1/auth/config") return json(config);
    calls.push(path);
    if (path === "/api/v1/audits") {
      assert.equal(options.headers.get("Authorization"), "Bearer linked-token");
      return json([{ audit_id: "owned-audit" }]);
    }
    return json({ user_id: guestId });
  }, () => () => client);
  await manager.start();
  await manager.linkGuestEmail("reader@example.com");
  assert.equal(manager.currentState().kind, "linking");
  await manager.verifyEmailOtp("654321");
  assert.equal(manager.currentState().userId, guestId);
  assert.deepEqual(await manager.request("/api/v1/audits"), [{ audit_id: "owned-audit" }]);
  assert.deepEqual(calls.slice(0, 3), [
    { email: "reader@example.com" },
    { email: "reader@example.com", token: "654321", type: "email_change" },
    "/api/v1/account/sync",
  ]);
});

test("guest identity conflict never syncs or switches ownership", async () => {
  const guest = { id: "guest-safe", is_anonymous: true };
  let syncs = 0;
  const client = { auth: {
    getSession: async () => ({ data: { session: { access_token: "guest", user: guest } } }),
    getUser: async () => ({ data: { user: guest } }),
    updateUser: async () => ({ error: { code: "email_exists" } }),
  } };
  const manager = createManager(async (path) => {
    if (path === "/api/v1/auth/config") return json(config);
    syncs++;
    return json({});
  }, () => () => client);
  await manager.start();
  await assert.rejects(manager.linkGuestEmail("taken@example.com"), /will not be merged automatically/);
  assert.equal(manager.currentState().userId, guest.id);
  assert.equal(manager.currentState().kind, "guest");
  assert.equal(syncs, 0);
});

test("Google direct sign-in and guest linking use different Supabase methods", async () => {
  let session = null;
  const calls = [];
  const client = { auth: {
    getSession: async () => ({ data: { session } }),
    signInWithOAuth: async (input) => (calls.push(["direct", input.provider]), { error: null }),
    signInAnonymously: async () => {
      session = { access_token: "guest", user: { id: "guest-1", is_anonymous: true } };
      return { data: { session } };
    },
    linkIdentity: async (input) => (calls.push(["link", input.provider]), { error: null }),
  } };
  const manager = createManager(async () => json(config), () => () => client);
  await manager.signInWithGoogle();
  await manager.continueAsGuest();
  await manager.linkGuestGoogle();
  assert.deepEqual(calls, [["direct", "google"], ["link", "google"]]);
  assert.equal(manager.currentState().userId, "guest-1");
});

test("Google link return accepts only the original guest user ID", async () => {
  const oldStorage = globalThis.sessionStorage;
  const values = new Map();
  globalThis.sessionStorage = {
    getItem: (key) => values.get(key) || null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  };
  try {
    values.set("claimtrellis-link-user-id", "guest-constant");
    const user = { id: "guest-constant", is_anonymous: false, email: "reader@example.com" };
    const client = { auth: {
      getSession: async () => ({ data: { session: { access_token: "linked", user } } }),
      getUser: async () => ({ data: { user } }),
    } };
    const manager = createManager(async () => json(config), () => () => client);
    await manager.start();
    assert.equal(manager.currentState().kind, "permanent");
    assert.equal(manager.currentState().userId, "guest-constant");
    assert.equal(values.size, 0);

    values.set("claimtrellis-link-user-id", "guest-constant");
    const wrong = { ...user, id: "different-account" };
    const conflict = createManager(async () => json(config), () => () => ({
      auth: {
        getSession: async () => ({ data: { session: { access_token: "wrong", user: wrong } } }),
        getUser: async () => ({ data: { user: wrong } }),
      },
    }));
    await assert.rejects(conflict.start(), /will not be merged automatically/);
    assert.equal(conflict.currentState().kind, "error");
    assert.equal(values.get("claimtrellis-link-user-id"), "guest-constant");
    await assert.rejects(conflict.start(), /will not be merged automatically/);
  } finally {
    globalThis.sessionStorage = oldStorage;
  }
});

test("permanent sign-out returns to signed-out without making a guest", async () => {
  let signIns = 0;
  let session = { access_token: "permanent", user: { id: "reader", is_anonymous: false } };
  const client = { auth: {
    getSession: async () => ({ data: { session } }),
    getUser: async () => ({ data: { user: session?.user } }),
    signOut: async () => (session = null, { error: null }),
    signInAnonymously: async () => (signIns++, { error: null }),
  } };
  const manager = createManager(async () => json(config), () => () => client);
  await manager.start();
  await manager.signOut();
  assert.equal(manager.currentState().kind, "signed_out");
  assert.equal(signIns, 0);
});

test("switching from a guest requires the explicit switch operation and never merges audits", async () => {
  let session = { access_token: "guest", user: { id: "original-guest", is_anonymous: true } };
  let signOuts = 0;
  const client = { auth: {
    getSession: async () => ({ data: { session } }),
    signOut: async () => (signOuts++, session = null, { error: null }),
  } };
  const manager = createManager(async () => json(config), () => () => client);
  await manager.start();
  assert.equal(manager.currentState().userId, "original-guest");
  assert.equal(signOuts, 0);
  await manager.switchToExistingAccount();
  assert.equal(manager.currentState().kind, "signed_out");
  assert.equal(signOuts, 1);
});

function sessionFixture(anonymous = false) {
  let session = { access_token: "test-token", user: { id: "original", is_anonymous: anonymous } };
  let listener;
  let signOuts = 0;
  const client = { auth: {
    getSession: async () => ({ data: { session } }),
    getUser: async () => ({ data: { user: session?.user } }),
    onAuthStateChange: (callback) => {
      listener = callback;
      return { data: { subscription: { unsubscribe() {} } } };
    },
    signOut: async () => { signOuts++; session = null; listener?.("SIGNED_OUT", null); return {}; },
    signInAnonymously: () => assert.fail("must not create another guest"),
    updateUser: async () => ({}),
  } };
  return {
    client,
    manager: createManager(async () => json(config), () => () => client),
    setUser: (user) => { session = user ? { access_token: "test-token", user } : null; },
    emit: (event) => listener(event, session),
    signOuts: () => signOuts,
  };
}

test("sign-out rechecks a guest cached before the same identity became permanent", async () => {
  const f = sessionFixture(true);
  await f.manager.start();
  f.setUser({ id: "original", is_anonymous: false });
  await f.manager.signOut();
  assert.equal(f.signOuts(), 1);
  assert.equal(f.manager.currentState().kind, "signed_out");
});

test("duplicate and already-completed sign-out are idempotent", async () => {
  const f = sessionFixture();
  await f.manager.start();
  await Promise.all([f.manager.signOut(), f.manager.signOut()]);
  await f.manager.signOut();
  assert.equal(f.signOuts(), 1);
  assert.equal(f.manager.currentState().kind, "signed_out");
});

test("sign-out still protects a genuine guest workspace", async () => {
  const f = sessionFixture(true);
  await f.manager.start();
  await assert.rejects(f.manager.signOut(), /Save your guest workspace/);
  assert.equal(f.signOuts(), 0);
  assert.equal(f.manager.currentState().userId, "original");
});

test("Supabase identity updates and cross-tab sign-out reach UI listeners", async () => {
  const f = sessionFixture(true);
  await f.manager.start();
  const changes = [];
  f.manager.onAuthStateChange((state) => changes.push(state.kind));
  f.setUser({ id: "original", is_anonymous: false });
  f.emit("USER_UPDATED");
  f.emit("TOKEN_REFRESHED");
  f.setUser(null);
  f.emit("SIGNED_OUT");
  assert.deepEqual(changes, ["permanent", "signed_out"]);
});

test("Continue as guest while linking reuses the guest and preserves OTP verification", async () => {
  const f = sessionFixture(true);
  await f.manager.linkGuestEmail("reader@example.com");
  assert.equal((await f.manager.continueAsGuest()).kind, "linking");
  assert.equal(f.manager.currentState().userId, "original");
});

test("an unexpected identity during linking blocks protected requests", async () => {
  const f = sessionFixture(true);
  await f.manager.linkGuestEmail("reader@example.com");
  f.setUser({ id: "other-account", is_anonymous: false });
  f.emit("SIGNED_IN");
  assert.equal(f.manager.currentState().kind, "error");
  await assert.rejects(f.manager.request("/api/v1/audits"), /session changed/);
  assert.equal(f.manager.keepGuestWorkspace().kind, "error");
});

test("failed email verification cannot expose a different account's data", async () => {
  const f = sessionFixture(true);
  await f.manager.linkGuestEmail("reader@example.com");
  f.client.auth.verifyOtp = async () => {
    f.setUser({ id: "other-account", is_anonymous: false });
    return { data: {} };
  };
  await assert.rejects(f.manager.verifyEmailOtp("123456"), /will not be merged/);
  await assert.rejects(f.manager.request("/api/v1/account"), /session changed/);
});

test("non-conflict email and Google failures do not claim the identity is taken", async () => {
  const f = sessionFixture(true);
  f.client.auth.updateUser = async () => ({ error: { code: "over_email_send_rate_limit" } });
  f.client.auth.linkIdentity = async () => ({ error: { code: "provider_disabled" } });
  await assert.rejects(f.manager.linkGuestEmail("reader@example.com"), /Could not send the linking code/);
  await assert.rejects(f.manager.linkGuestGoogle(), /Google linking could not start/);
  assert.equal(f.manager.currentState().kind, "guest");
  assert.equal(f.manager.currentState().userId, "original");
});

test("Google callback conflict preserves the original guest and exposes recoverable feedback", async (t) => {
  const oldStorage = globalThis.sessionStorage;
  const oldLocation = globalThis.location;
  t.after(() => { globalThis.sessionStorage = oldStorage; globalThis.location = oldLocation; });
  const values = new Map([["claimtrellis-link-user-id", "original"]]);
  globalThis.sessionStorage = {
    getItem: (key) => values.get(key), removeItem: (key) => values.delete(key),
  };
  globalThis.location = { hash: "#error=server_error&error_code=identity_already_exists" };
  const f = sessionFixture(true);
  await f.manager.start();
  assert.equal(f.manager.currentState().kind, "guest");
  assert.equal(f.manager.currentState().userId, "original");
  assert.match(f.manager.currentState().notice, /will not be merged automatically/);
  f.manager.keepGuestWorkspace();
  assert.equal(f.manager.currentState().notice, null);
  assert.equal(values.size, 0);
});

test("a response that finishes after sign-out cannot restore prior account data", async () => {
  const f = sessionFixture();
  let finish;
  let started;
  const began = new Promise((resolve) => { started = resolve; });
  const manager = createManager(async (path) => {
    if (path === "/api/v1/auth/config") return json(config);
    started();
    return new Promise((resolve) => { finish = resolve; });
  }, () => () => f.client);
  await manager.start();
  const request = manager.request("/api/v1/audits");
  await began;
  await manager.signOut();
  finish(json([{ audit_id: "old-private-audit" }]));
  await assert.rejects(request, /session changed/);
});
