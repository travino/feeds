# feeds-proxy

Minimal HTTPS-only CORS proxy: `GET /?url=https://...` fetches the target and
re-serves it with `access-control-allow-origin: *` and a 15-minute edge cache.

Used as the optional "CORS proxy prefix" in feedseek's browser reader
(`site/reader.html`) for feeds whose origin doesn't send CORS
headers. Not tied to feedseek or kanarek specifically — either one, or
anything else in the account, can point at it.

The same Worker also exposes Feedseek's read-only remote MCP endpoint at
`POST https://feeds.trfny.com/mcp`. The MCP route is composed in `src/app.js`
so the existing constrained proxy implementation remains independent.

## Behavior

- `POST /mcp` exposes the read-only `search`, `fetch`, and `recent` Feedseek tools.
- `GET /download-soundtracks?path=/...` is a host-locked fetch path for `download-soundtracks.com`, with a browser user-agent and a 20-second timeout. It exists so scheduled Feedseek generation can avoid origin blocks on GitHub-hosted runner IPs without turning the Worker into a general forward proxy.
- No `url` param, or non-`https://` target → `400`
- Upstream fetch fails or times out (8s) → `502`
- Otherwise: passes through status + body, forces `access-control-allow-origin: *`
  and `cache-control: public, max-age=900`, defaults content-type to
  `application/xml; charset=utf-8` when upstream doesn't send one

See [`../docs/chatgpt/`](../docs/chatgpt/) for the ChatGPT app data flow,
testing, installation, and submission notes.

## Deploy

```
npm install
npm run deploy
```

Live at `feeds-proxy.travny.workers.dev`; the Feedseek MCP endpoint uses the
`feeds.trfny.com` custom domain.
