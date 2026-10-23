/**
 * Test page for the bot_block scenario: always answers HTTP 403, like a bot wall that
 * nothing gets through. Static files can't set a status, so this one is a route handler.
 */

const PAGE = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Access denied</title>
<style>
  body { margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 16px;
    font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; color: #1f2430; background: #f3f4f6; }
  .box { max-width: 520px; background: #fff; border: 1px solid #dde1e8; border-radius: 12px; padding: 28px; }
  h1 { margin: 0 0 8px; font-size: 24px; }
  p { margin: 0 0 12px; color: #5d6576; }
  code { font-size: 13px; color: #1f2430; }
  footer { margin-top: 18px; font-size: 12px; color: #8a929b; }
</style>
</head>
<body>
  <div class="box">
    <h1>Access denied</h1>
    <p>Error 403. Our bot detection flagged this request as automated traffic, so the Harbor Lamp
      product page is not available to it.</p>
    <p>Reference: <code>__REF__</code></p>
    <footer>Test page for Agent Failure Autopsy. It answers every visitor this way.</footer>
  </div>
</body>
</html>
`;

export async function GET(request: Request) {
  // Reading the request makes this run per request (Cache Components), so it is never
  // prerendered into a static 200.
  const ref = `${Date.now().toString(36)}-${(request.headers.get("x-vercel-id") ?? "local").slice(-8)}`;
  return new Response(PAGE.replace("__REF__", ref), {
    status: 403,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store",
      "x-robots-tag": "noindex",
    },
  });
}
