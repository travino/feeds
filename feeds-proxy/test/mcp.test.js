import assert from "node:assert/strict";
import test from "node:test";

import { mcpResponse } from "../src/mcp.js";

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

const opaqueId = "openai:dGFnOmV4YW1wbGU";
const indexPayload = {
  indexed_from: "2026-08-24T00:00:00Z",
  items: [
    {
      id: opaqueId,
      source_key: "openai",
      source: "OpenAI",
      title: "New coding model",
      url: "https://example.com/a",
      summary: "Agents and coding",
      published_at: "2026-09-07T10:00:00Z",
      tags: ["AI"],
    },
    {
      id: "reuters:eA",
      source_key: "reuters",
      source: "Reuters",
      title: "Markets",
      url: "https://example.com/b",
      summary: "Daily markets",
      published_at: "2026-09-07T11:00:00Z",
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

test("lists standard search/fetch plus read-only recent", async () => {
  const body = await (await call("tools/list")).json();
  assert.deepEqual(
    body.result.tools.map((tool) => tool.name),
    ["search", "fetch", "recent"],
  );
  const search = body.result.tools[0];
  assert.deepEqual(search.inputSchema.required, ["query"]);
  assert.deepEqual(Object.keys(search.inputSchema.properties), ["query"]);
  for (const tool of body.result.tools) {
    assert.equal(tool.annotations.readOnlyHint, true);
    assert.equal(tool.annotations.destructiveHint, false);
    assert.equal(tool.annotations.openWorldHint, false);
    assert.ok(tool.outputSchema);
  }
});

test("standard search returns only id title and canonical url", async () => {
  await withFetch(
    async () => new Response(JSON.stringify(indexPayload), { status: 200 }),
    async () => {
      const body = await (
        await call("tools/call", {
          name: "search",
          arguments: { query: "coding" },
        })
      ).json();
      assert.deepEqual(body.result.structuredContent, {
        results: [
          {
            id: opaqueId,
            title: "New coding model",
            url: "https://example.com/a",
          },
        ],
      });
      assert.equal(body.result.content.length, 1);
      assert.equal(body.result.content[0].type, "text");
    },
  );
});

test("recent honors time and source filters and returns summaries", async () => {
  await withFetch(
    async () => new Response(JSON.stringify(indexPayload), { status: 200 }),
    async () => {
      const body = await (
        await call("tools/call", {
          name: "recent",
          arguments: {
            query: "coding",
            sources: ["openai"],
            since: "2026-09-07T00:00:00Z",
          },
        })
      ).json();
      assert.equal(body.result.structuredContent.count, 1);
      assert.equal(
        body.result.structuredContent.entries[0].summary,
        "Agents and coding",
      );
    },
  );
});

test("fetch returns the standard document shape with metadata", async () => {
  await withFetch(
    async (url) => {
      assert.equal(
        String(url),
        "https://raw.githubusercontent.com/trvny/feedseek/main/feeds/feed_openai.json",
      );
      return new Response(
        JSON.stringify({
          title: "OpenAI",
          items: [
            {
              id: "tag:example",
              title: "Full story",
              url: "https://example.com/full",
              content_text: "Complete text",
              date_published: "2026-09-07T10:00:00Z",
              tags: ["AI"],
            },
          ],
        }),
        { status: 200 },
      );
    },
    async () => {
      const body = await (
        await call("tools/call", {
          name: "fetch",
          arguments: { id: opaqueId },
        })
      ).json();
      assert.equal(body.result.structuredContent.title, "Full story");
      assert.equal(body.result.structuredContent.text, "Complete text");
      assert.equal(body.result.structuredContent.metadata.source_key, "openai");
    },
  );
});

test("tool errors are model-visible and preflight permits POST", async () => {
  const malformed = await (
    await call("tools/call", {
      name: "fetch",
      arguments: { id: "nope" },
    })
  ).json();
  assert.equal(malformed.result.isError, true);
  assert.equal(malformed.result.structuredContent, undefined);
  assert.match(malformed.result.content[0].text, /invalid Feedseek result id/);

  const options = await mcpResponse(
    new Request("https://feeds.trfny.com/mcp", { method: "OPTIONS" }),
  );
  assert.equal(options.status, 204);
  assert.match(options.headers.get("access-control-allow-methods"), /POST/);
});

test("notifications are accepted without a JSON-RPC response body", async () => {
  const response = await mcpResponse(
    new Request("https://feeds.trfny.com/mcp", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        jsonrpc: "2.0",
        method: "notifications/initialized",
      }),
    }),
  );
  assert.equal(response.status, 202);
  assert.equal(await response.text(), "");
});
