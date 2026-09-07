import assert from "node:assert/strict";
import test from "node:test";

import app from "../src/app.js";

const challengeUrl = "https://feeds.trfny.com/.well-known/openai-apps-challenge";

test("serves the OpenAI domain verification token as plain text", async () => {
  const response = await app.fetch(new Request(challengeUrl), {
    OPENAI_APPS_CHALLENGE: "challenge-token-123",
  });

  assert.equal(response.status, 200);
  assert.equal(response.headers.get("content-type"), "text/plain; charset=utf-8");
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.equal(await response.text(), "challenge-token-123");
});

test("keeps the verification endpoint closed until a token is configured", async () => {
  const response = await app.fetch(new Request(challengeUrl), {});
  assert.equal(response.status, 404);
});

test("rejects write methods on the verification endpoint", async () => {
  const response = await app.fetch(
    new Request(challengeUrl, { method: "POST" }),
    { OPENAI_APPS_CHALLENGE: "challenge-token-123" },
  );

  assert.equal(response.status, 405);
  assert.equal(response.headers.get("allow"), "GET, HEAD");
});
