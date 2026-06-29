import type { NextRequest } from "next/server";

/** Same-origin proxy for product 2D icons.
 *
 *  The icon bucket serves <img> GETs but no CORS headers, so drawing those icons on the
 *  Konva canvas TAINTS it - and the AI-preview export (stage.toDataURL) then throws a
 *  SecurityError. Routing the icons through this same-origin endpoint (which echoes
 *  permissive CORS) keeps the canvas exportable. Restricted to the known icon host. */
const ALLOWED_HOSTS = new Set([
  "zory-temporary-uploads-backup.s3.ap-south-1.amazonaws.com",
]);

export async function GET(req: NextRequest) {
  const raw = req.nextUrl.searchParams.get("u");
  if (!raw) return new Response("missing url", { status: 400 });

  let target: URL;
  try {
    target = new URL(raw);
  } catch {
    return new Response("bad url", { status: 400 });
  }
  if (target.protocol !== "https:" || !ALLOWED_HOSTS.has(target.host)) {
    return new Response("forbidden host", { status: 403 });
  }

  let upstream: Response;
  try {
    upstream = await fetch(target.toString());
  } catch {
    return new Response("upstream fetch failed", { status: 502 });
  }
  if (!upstream.ok || !upstream.body) {
    return new Response("upstream error", { status: upstream.status || 502 });
  }

  return new Response(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": upstream.headers.get("content-type") || "image/svg+xml",
      "Cache-Control": "public, max-age=86400, immutable",
      "Access-Control-Allow-Origin": "*",
    },
  });
}
