// 치지직 신청곡 봇 인증 서버 (Cloudflare Workers)
// Client Secret 은 이 서버에만 두고, 각 스트리머 PC 의 봇은 토큰만 받아서 씁니다.
//
// 필요한 Secret (wrangler secret put 으로 등록):
//   CHZZK_CLIENT_ID, CHZZK_CLIENT_SECRET
//
// 엔드포인트
//   GET  /login?port=8080&nonce=xxx  → 치지직 로그인 페이지로 이동
//   GET  /callback                   → 치지직이 돌려보내는 곳. 토큰 발급 후 http://localhost:{port}/auth 로 전달
//   POST /refresh {refreshToken}     → 토큰 갱신

const API = "https://openapi.chzzk.naver.com";
const STATE_TTL_MS = 10 * 60 * 1000;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    try {
      if (url.pathname === "/login" && request.method === "GET") return await login(url, env);
      if (url.pathname === "/callback" && request.method === "GET") return await callback(url, env);
      if (url.pathname === "/refresh" && request.method === "POST") return await refresh(request, env);
      return new Response("Chzzk songbot auth server", { headers: { "content-type": "text/plain; charset=utf-8" } });
    } catch (e) {
      return new Response(`오류: ${e.message}`, { status: 500, headers: { "content-type": "text/plain; charset=utf-8" } });
    }
  },
};

// ---------- 로그인 ----------
async function login(url, env) {
  const port = parseInt(url.searchParams.get("port") || "", 10);
  const nonce = url.searchParams.get("nonce") || "";
  if (!(port > 0 && port < 65536) || !/^[A-Za-z0-9_-]{8,64}$/.test(nonce)) {
    return text("잘못된 요청입니다.", 400);
  }
  const state = await signState(env, { p: port, n: nonce, e: Date.now() + STATE_TTL_MS });
  const target = new URL("https://chzzk.naver.com/account-interlock");
  target.searchParams.set("clientId", env.CHZZK_CLIENT_ID);
  target.searchParams.set("redirectUri", `${url.origin}/callback`);
  target.searchParams.set("state", state);
  return Response.redirect(target.toString(), 302);
}

async function callback(url, env) {
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state") || "";
  const data = await verifyState(env, state);
  if (!code || !data) return text("로그인 요청이 만료되었거나 잘못되었습니다. 봇에서 다시 로그인해 주세요.", 400);

  const back = new URLSearchParams({ nonce: data.n });
  try {
    const content = await tokenRequest({
      grantType: "authorization_code",
      clientId: env.CHZZK_CLIENT_ID,
      clientSecret: env.CHZZK_CLIENT_SECRET,
      code,
      state,
    });
    back.set("accessToken", content.accessToken);
    back.set("refreshToken", content.refreshToken);
    back.set("expiresIn", String(content.expiresIn || 86400));
  } catch (e) {
    back.set("error", e.message);
  }
  // 토큰은 URL 조각(#)으로 넘겨서 서버 로그에 남지 않게 합니다.
  return Response.redirect(`http://localhost:${data.p}/auth#${back.toString()}`, 302);
}

async function refresh(request, env) {
  let body;
  try {
    body = await request.json();
  } catch {
    return json({ error: "잘못된 요청" }, 400);
  }
  if (typeof body.refreshToken !== "string" || !body.refreshToken) return json({ error: "refreshToken 필요" }, 400);
  try {
    const content = await tokenRequest({
      grantType: "refresh_token",
      refreshToken: body.refreshToken,
      clientId: env.CHZZK_CLIENT_ID,
      clientSecret: env.CHZZK_CLIENT_SECRET,
    });
    return json({ content });
  } catch (e) {
    return json({ error: e.message }, e.status || 502);
  }
}

// ---------- 치지직 토큰 API ----------
async function tokenRequest(body) {
  const r = await fetch(`${API}/auth/v1/token`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok || !data.content) {
    const err = new Error(`토큰 발급 실패 (${r.status}) ${data.message || ""}`.trim());
    // 401 = 사용자 토큰 문제(다시 로그인 필요), 502 = 서버 설정(Client ID/Secret) 문제 등
    const clientProblem = /CLIENT/i.test(data.message || "");
    err.status = (r.status === 401 || r.status === 400) && !clientProblem ? 401 : 502;
    throw err;
  }
  return data.content;
}

// ---------- state 서명 (서버에 저장소 없이 위조 방지) ----------
async function hmacKey(env) {
  return crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode("state:" + env.CHZZK_CLIENT_SECRET),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign", "verify"],
  );
}

function b64url(bytes) {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function unb64url(s) {
  const bin = atob(s.replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
}

async function signState(env, obj) {
  const payload = b64url(new TextEncoder().encode(JSON.stringify(obj)));
  const sig = await crypto.subtle.sign("HMAC", await hmacKey(env), new TextEncoder().encode(payload));
  return `${payload}.${b64url(new Uint8Array(sig))}`;
}

async function verifyState(env, state) {
  const [payload, sig] = state.split(".");
  if (!payload || !sig) return null;
  try {
    const ok = await crypto.subtle.verify("HMAC", await hmacKey(env), unb64url(sig), new TextEncoder().encode(payload));
    if (!ok) return null;
    const obj = JSON.parse(new TextDecoder().decode(unb64url(payload)));
    return obj.e > Date.now() ? obj : null;
  } catch {
    return null;
  }
}

function text(msg, status = 200) {
  return new Response(msg, { status, headers: { "content-type": "text/plain; charset=utf-8" } });
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json" } });
}
