import assert from "node:assert/strict";
import test from "node:test";

import { htmlToText, mcpResponse, parseWhen } from "../src/mcp.js";

const call = (method, params = {}, id = 1, protocol = "2026-07-28") =>
  mcpResponse(
    new Request("https://feeds.trfny.com/mcp", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "mcp-protocol-version": protocol,
      },
      body: JSON.stringify({ jsonrpc: "2.0", id, method, params }),
    }),
  );

async function withFetch(mockFetch, run) {
  const original = globalThis.fetch;
  globalThis.fetch = mockFetch;
  try {
    return await run();
  } finally {
    globalThis.fetch = original;
  }
}

const revision = "a".repeat(40);
const opaqueId = `${revision}.openai:dGFnOmV4YW1wbGU`;
const indexPayload = {
  indexed_from: "2026-09-02T00:00:00Z",
  truncated: true,
  skipped_feeds: [{ source_key: "broken", reason: "invalid_json_feed" }],
  revision,
  items: [
    {
      id: opaqueId,
      source_key: "openai",
      source: "OpenAI",
      title: "Żółć coding model",
      url: "https://example.com/a",
      summary: "Agents and coding",
      published_at: "2026-08-01T10:00:00Z",
      modified_at: "2026-09-07T10:00:00Z",
      tags: ["AI"],
    },
    {
      id: `${revision}.reuters:eA`,
      source_key: "reuters",
      source: "Reuters",
      title: "Markets",
      url: "https://example.com/b",
      summary: "Daily markets",
      published_at: "2026-09-07T11:00:00Z",
      modified_at: null,
      tags: [],
    },
  ],
};

test("negotiates initialize and advertises tool capability", async () => {
  const response = await call("initialize", {
    protocolVersion: "2026-07-28",
    capabilities: {},
    clientInfo: { name: "test", version: "1" },
  });
  const body = await response.json();
  assert.equal(response.status, 200);
  assert.equal(body.result.protocolVersion, "2026-07-28");
  assert.equal(body.result.resultType, "complete");
  assert.deepEqual(body.result.capabilities, { tools: {} });
});

test("unsupported protocol returns modern error with HTTP 400", async () => {
  const response = await call("initialize", { protocolVersion: "1900-01-01" });
  const body = await response.json();
  assert.equal(response.status, 400);
  assert.equal(body.error.code, -32022);
  assert.equal(body.error.data.requested, "1900-01-01");
  assert.ok(body.error.data.supported.includes("2026-07-28"));
});

test("supports modern server discovery", async () => {
  const body = await (await call("server/discover")).json();
  assert.equal(body.result.resultType, "complete");
  assert.ok(body.result.supportedVersions.includes("2026-07-28"));
  assert.equal(body.result.cacheScope, "public");
});

test("modern tools/list includes cache metadata", async () => {
  const body = await (await call("tools/list")).json();
  assert.equal(body.result.resultType, "complete");
  assert.equal(body.result.cacheScope, "public");
  assert.ok(Number.isInteger(body.result.ttlMs));
  assert.deepEqual(body.result.tools.map((tool) => tool.name), ["search", "fetch", "recent"]);
  for (const tool of body.result.tools) {
    assert.equal(tool.annotations.readOnlyHint, true);
    assert.equal(tool.annotations.destructiveHint, false);
    assert.ok(tool.outputSchema);
  }
});

test("legacy tools/list remains compatible", async () => {
  const body = await (await call("tools/list", {}, 1, "2025-11-25")).json();
  assert.equal(body.result.resultType, undefined);
  assert.equal(body.result.ttlMs, undefined);
  assert.equal(body.result.tools.length, 3);
});

test("strict RFC 3339 parser rejects loose and impossible dates", () => {
  assert.notEqual(parseWhen("2026-09-07T10:00:00Z"), null);
  assert.notEqual(parseWhen("2026-09-07T12:00:00+02:00"), null);
  assert.equal(parseWhen("2026-09-07"), null);
  assert.equal(parseWhen("2026-09-07T10:00:00"), null);
  assert.equal(parseWhen("2026-02-30T10:00:00Z"), null);
  assert.equal(parseWhen("09/07/2026 10:00"), null);
});

test("standard search normalizes diacritics and returns connector shape", async () => {
  await withFetch(
    async () => new Response(JSON.stringify(indexPayload), { status: 200 }),
    async () => {
      const body = await (
        await call("tools/call", { name: "search", arguments: { query: "zolc" } })
      ).json();
      assert.deepEqual(body.result.structuredContent.results[0], {
        id: opaqueId,
        title: "Żółć coding model",
        url: "https://example.com/a",
      });
    },
  );
});

test("recent reports coverage and uses newest publication or modification time", async () => {
  await withFetch(
    async () => new Response(JSON.stringify(indexPayload), { status: 200 }),
    async () => {
      const body = await (
        await call("tools/call", {
          name: "recent",
          arguments: { query: "coding", sources: ["openai"], since: "2026-09-07T00:00:00Z" },
        })
      ).json();
      const result = body.result.structuredContent;
      assert.equal(result.count, 1);
      assert.equal(result.truncated, true);
      assert.deepEqual(result.skipped_sources, ["broken"]);
      assert.equal(result.entries[0].modified_at, "2026-09-07T10:00:00Z");
    },
  );
});

test("recent rejects non-RFC and impossible cutoffs before fetching", async () => {
  for (const since of ["2026-09-07", "2026-09-07T10:00:00", "2026-02-30T10:00:00Z"]) {
    const body = await (
      await call("tools/call", { name: "recent", arguments: { since } })
    ).json();
    assert.equal(body.result.isError, true);
    assert.match(body.result.content[0].text, /RFC 3339/);
  }
});

test("fetch is pinned to revision and uses external_url fallback", async () => {
  await withFetch(
    async (url) => {
      assert.equal(String(url), `https://raw.githubusercontent.com/trvny/feedseek/${revision}/feeds/feed_openai.json`);
      return new Response(JSON.stringify({
        title: "OpenAI",
        items: [{
          id: "tag:example",
          title: "Full story",
          external_url: "https://example.com/full",
          content_text: "Use <T> & keep it",
        }],
      }), { status: 200 });
    },
    async () => {
      const body = await (
        await call("tools/call", { name: "fetch", arguments: { id: opaqueId } })
      ).json();
      assert.equal(body.result.structuredContent.text, "Use <T> & keep it");
      assert.equal(body.result.structuredContent.url, "https://example.com/full");
    },
  );
});

test("HTML conversion decodes markup without eating literal less-than text", () => {
  assert.equal(
    htmlToText("<p>Hello &amp; <strong>world</strong>.</p><script>bad()</script>"),
    "Hello & world.",
  );
  assert.equal(htmlToText("<p>2 < 3 and 4 > 1</p>"), "2 < 3 and 4 > 1");
});

test("tool arguments are validated server-side", async () => {
  const extra = await (
    await call("tools/call", { name: "search", arguments: { query: "AI", limit: 10 } })
  ).json();
  assert.equal(extra.result.isError, true);
  assert.match(extra.result.content[0].text, /unexpected argument: limit/);
});

test("tool errors are model-visible and preflight permits POST", async () => {
  const malformed = await (
    await call("tools/call", { name: "fetch", arguments: { id: "nope" } })
  ).json();
  assert.equal(malformed.result.isError, true);
  const options = await mcpResponse(new Request("https://feeds.trfny.com/mcp", { method: "OPTIONS" }));
  assert.equal(options.status, 204);
  assert.match(options.headers.get("access-control-allow-methods"), /POST/);
});

test("notifications are accepted without a JSON-RPC response body", async () => {
  const response = await mcpResponse(new Request("https://feeds.trfny.com/mcp", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" }),
  }));
  assert.equal(response.status, 202);
  assert.equal(await response.text(), "");
});
