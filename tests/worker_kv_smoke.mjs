import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";

const sourcePath = path.resolve("deploy/remote/vitalab/cloudflare/pages_worker.template.js");
const source = await fs.readFile(sourcePath, "utf8");
const tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), "vitalab-worker-"));
const modulePath = path.join(tmpDir, "worker.mjs");
await fs.writeFile(modulePath, source, "utf8");

const worker = (await import(`file://${modulePath}`)).default;

let proxiedUrl = null;
globalThis.fetch = async (request) => {
  proxiedUrl = request.url;
  return new Response(JSON.stringify({ status: "ok" }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
};

const assets = {
  fetch: async () => new Response("asset", { status: 200 }),
};

let response = await worker.fetch(new Request("https://pages.example/api/health"), {
  ASSETS: assets,
  VITALAB_ORIGIN_KV: {
    get: async (key) => {
      assert.equal(key, "current_backend_origin");
      return "https://shade-temp-raising-vendor.trycloudflare.com";
    },
  },
});
assert.equal(response.status, 200);
assert.equal(proxiedUrl, "https://shade-temp-raising-vendor.trycloudflare.com/api/health");

response = await worker.fetch(new Request("https://pages.example/api/health"), {
  ASSETS: assets,
  VITALAB_ORIGIN_KV: { get: async () => null },
});
assert.equal(response.status, 503);
assert.equal((await response.json()).error, "backend_origin_unavailable");

response = await worker.fetch(new Request("https://pages.example/api/health"), {
  ASSETS: assets,
  VITALAB_ORIGIN_KV: { get: async () => "http://bad.trycloudflare.com" },
});
assert.equal(response.status, 503);

response = await worker.fetch(new Request("https://pages.example/api/health", { method: "OPTIONS" }), {
  ASSETS: assets,
  VITALAB_ORIGIN_KV: { get: async () => null },
});
assert.equal(response.status, 204);

response = await worker.fetch(new Request("https://pages.example/"), {
  ASSETS: assets,
  VITALAB_ORIGIN_KV: { get: async () => null },
});
assert.equal(response.status, 200);
assert.equal(await response.text(), "asset");
