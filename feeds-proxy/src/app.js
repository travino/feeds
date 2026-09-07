import proxyWorker from "./index.js";
import { mcpResponse } from "./mcp.js";

export default {
  fetch(request, env, ctx) {
    if (new URL(request.url).pathname === "/mcp") return mcpResponse(request);
    return proxyWorker.fetch(request, env, ctx);
  },
};
