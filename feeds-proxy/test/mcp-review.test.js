import assert from "node:assert/strict";
import test from "node:test";

import { mcpResponse } from "../src/mcp.js";

const revision = "a".repeat(40);
const opaqueId = `${revision}.openai:dGFnOmV4YW1wbGU`;

const call = (params) =>
  mcpResponse(
    new Request("https://feeds.trfny.com/mcp", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "mcp-protocol-version": "2026-07-28",
      },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/call", params }),
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

test("short search terms match token boundaries", async () => {
  const payload = {
    indexed_from: "2026-09-02T00:00:00Z",
    truncated: false,
    skipped_feeds: [],
    items: [
      {
        id: opaqueId,
        source_key: "openai",
        source: "OpenAI",
        title: "Coding model",
        url: "https://example.com/ai",
        summary: "Agents",
        published_at: "2026-09-07T10:00:00Z",
        modified_at: null,
        tags: ["AI"],
      },
      {
        id: `${revision}.noise:bm9pc2U`,
        source_key: "noise",
        source: "Daily Digest",
        title: "Daily painting and airplanes",
        url: "https://example.com/noise",
        summary: "A daily airplane story",
        published_at: "2026-09-07T11:00:00Z",
        modified_at: null,
        tags: [],
      },
    ],
  };
  await withFetch(
    async () => new Response(JSON.stringify(payload), { status: 200 }),
    async () => {
      const body = await (
        await call({ name: "search", arguments: { query: "AI" } })
      ).json();
      assert.deepEqual(
        body.result.structuredContent.results.map((entry) => entry.id),
        [opaqueId],
      );
    },
  );
});

test("fetch preserves structural whitespace in content_text", async () => {
  await withFetch(
    async () =>
      new Response(
        JSON.stringify({
          title: "OpenAI",
          items: [
            {
              id: "tag:example",
              title: "Structured text",
              url: "https://example.com/full",
              content_text: "Paragraph one\n\n- item\tvalue\n  code",
            },
          ],
        }),
        { status: 200 },
      ),
    async () => {
      const body = await (
        await call({ name: "fetch", arguments: { id: opaqueId } })
      ).json();
      assert.equal(
        body.result.structuredContent.text,
        "Paragraph one\n\n- item\tvalue\n  code",
      );
    },
  );
});
