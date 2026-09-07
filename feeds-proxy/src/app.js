import proxyWorker from "./index.js";
import { mcpResponse } from "./mcp.js";

export default {
  /** @param {Request} request */
  fetch(request) {
    if (new URL(request.url).pathname === "/mcp") return mcpResponse(request);
    return proxyWorker.fetch(request);
  },
};
