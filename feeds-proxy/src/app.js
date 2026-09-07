import proxyWorker from "./index.js";
import { mcpResponse } from "./mcp.js";

const OPENAI_CHALLENGE_PATH = "/.well-known/openai-apps-challenge";

/**
 * @param {Request} request
 * @param {{ OPENAI_APPS_CHALLENGE?: string } | undefined} env
 */
function openAiChallengeResponse(request, env) {
  const token = env?.OPENAI_APPS_CHALLENGE?.trim();
  if (!token) return new Response("Not Found", { status: 404 });
  if (request.method !== "GET" && request.method !== "HEAD") {
    return new Response("Method Not Allowed", {
      status: 405,
      headers: { allow: "GET, HEAD" },
    });
  }
  return new Response(request.method === "HEAD" ? null : token, {
    headers: {
      "cache-control": "no-store",
      "content-type": "text/plain; charset=utf-8",
    },
  });
}

export default {
  /**
   * @param {Request} request
   * @param {{ OPENAI_APPS_CHALLENGE?: string } | undefined} env
   */
  fetch(request, env) {
    const pathname = new URL(request.url).pathname;
    if (pathname === "/mcp") return mcpResponse(request);
    if (pathname === OPENAI_CHALLENGE_PATH) return openAiChallengeResponse(request, env);
    return proxyWorker.fetch(request);
  },
};
