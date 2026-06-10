const DEFAULT_ORIGIN_KEY = "current_backend_origin";
const DEFAULT_ALLOWED_BACKEND_HOST_SUFFIXES = ".trycloudflare.com";
const STATIC_SECURITY_HEADERS = {
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "strict-origin-when-cross-origin",
};
const API_CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Accept",
  "Access-Control-Max-Age": "86400",
};

function shouldProxy(pathname) {
  return pathname.startsWith("/api/") || pathname === "/api" || pathname.startsWith("/PDF/") || pathname === "/PDF";
}

function splitCsv(value, fallback) {
  return String(value || fallback)
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function hostMatchesSuffix(hostname, suffix) {
  const normalizedHost = String(hostname || "").toLowerCase();
  const normalizedSuffix = String(suffix || "").toLowerCase();
  if (!normalizedHost || !normalizedSuffix) {
    return false;
  }
  if (normalizedSuffix.startsWith(".")) {
    return normalizedHost.endsWith(normalizedSuffix) && normalizedHost.length > normalizedSuffix.length;
  }
  return normalizedHost === normalizedSuffix || normalizedHost.endsWith(`.${normalizedSuffix}`);
}

function normalizeBackendOrigin(rawOrigin, env) {
  const trimmed = String(rawOrigin || "").trim().replace(/\/+$/, "");
  if (!trimmed) {
    return null;
  }

  let parsed;
  try {
    parsed = new URL(trimmed);
  } catch {
    return null;
  }

  if (parsed.protocol !== "https:" || parsed.username || parsed.password || parsed.search || parsed.hash) {
    return null;
  }
  if (parsed.pathname && parsed.pathname !== "/") {
    return null;
  }

  const suffixes = splitCsv(env.ALLOWED_BACKEND_HOST_SUFFIXES, DEFAULT_ALLOWED_BACKEND_HOST_SUFFIXES);
  if (!suffixes.some((suffix) => hostMatchesSuffix(parsed.hostname, suffix))) {
    return null;
  }

  return parsed.origin;
}

async function resolveBackendOrigin(env) {
  if (!env || !env.VITALAB_ORIGIN_KV || typeof env.VITALAB_ORIGIN_KV.get !== "function") {
    return null;
  }
  const key = env.CLOUDFLARE_KV_ORIGIN_KEY || DEFAULT_ORIGIN_KEY;
  const rawOrigin = await env.VITALAB_ORIGIN_KV.get(key, "text");
  return normalizeBackendOrigin(rawOrigin, env);
}

function backendOriginUnavailable() {
  return new Response(JSON.stringify({ error: "backend_origin_unavailable" }), {
    status: 503,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      ...API_CORS_HEADERS,
    },
  });
}

function buildProxyRequest(request, targetUrl) {
  const headers = new Headers(request.headers);
  headers.delete("host");

  const init = {
    method: request.method,
    headers,
    redirect: "manual",
  };

  if (!["GET", "HEAD"].includes(request.method.toUpperCase())) {
    init.body = request.body;
  }

  return new Request(targetUrl, init);
}

function corsHeadersForRequest(request) {
  const headers = new Headers(API_CORS_HEADERS);
  const requestedHeaders = request.headers.get("Access-Control-Request-Headers");
  if (requestedHeaders) {
    headers.set("Access-Control-Allow-Headers", requestedHeaders);
  }
  return headers;
}

function addCorsHeaders(headers, request) {
  for (const [name, value] of corsHeadersForRequest(request).entries()) {
    headers.set(name, value);
  }
}

function handleCorsPreflight(request) {
  return new Response(null, {
    status: 204,
    headers: corsHeadersForRequest(request),
  });
}

async function proxyToBackend(request, env) {
  const backendOrigin = await resolveBackendOrigin(env);
  if (!backendOrigin) {
    return backendOriginUnavailable();
  }

  const url = new URL(request.url);
  const targetUrl = new URL(url.pathname + url.search, backendOrigin);
  let response;
  try {
    response = await fetch(buildProxyRequest(request, targetUrl.toString()));
  } catch {
    return new Response(JSON.stringify({ error: "backend_fetch_failed" }), {
      status: 502,
      headers: {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "no-store",
        ...API_CORS_HEADERS,
      },
    });
  }
  const headers = new Headers(response.headers);

  headers.set("Cache-Control", "no-store");
  addCorsHeaders(headers, request);
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

async function serveStatic(request, env) {
  const response = await env.ASSETS.fetch(request);
  const headers = new Headers(response.headers);

  for (const [name, value] of Object.entries(STATIC_SECURITY_HEADERS)) {
    headers.set(name, value);
  }

  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (shouldProxy(url.pathname)) {
      if (request.method.toUpperCase() === "OPTIONS") {
        return handleCorsPreflight(request);
      }
      return proxyToBackend(request, env);
    }

    return serveStatic(request, env);
  },
};
