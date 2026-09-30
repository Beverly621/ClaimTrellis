const assert = require("node:assert/strict");
const { test } = require("node:test");
const { createManager } = require("./auth.js");

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
};

test("new guest signs in anonymously before protected history and sends bearer token", async () => {
  const paths = [];
  let signIns = 0;
  let session = null;
  const client = {
    auth: {
      getSession: async () => ({ data: { session }, error: null }),
      signInAnonymously: async () => {
        signIns++;
        session = { access_token: "guest-token" };
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
  await assert.rejects(pending, /Guest sign-in is unavailable/);
  assert.equal(protectedCalls, 0);
});
