// SMA-898 viewport measurement: drives chrome-headless-shell over raw CDP
// (no Playwright on this VM). Usage: node measure.mjs <url> <width> <height> [tapCountry]
import { spawn } from "node:child_process";
const [url, W, H, tap] = process.argv.slice(2);
const BIN = process.env.HOME + "/.cache/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-linux64/chrome-headless-shell";
const port = 9300 + Math.floor(Math.random() * 500);
const isLocal = /127\.0\.0\.1|localhost/.test(url);
const args = ["--headless", "--no-sandbox", "--disable-gpu", `--remote-debugging-port=${port}`,
  "--user-data-dir=/tmp/sma898-chrome-" + port, "about:blank"];
if (!isLocal) args.push("--proxy-server=http://127.0.0.1:8898", "--proxy-bypass-list=localhost;127.0.0.1");
const proc = spawn(BIN, args, { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let wsUrl;
for (let i = 0; i < 50 && !wsUrl; i++) {
  await sleep(200);
  try { const j = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json(); wsUrl = j.find((t) => t.type === "page")?.webSocketDebuggerUrl; } catch {}
}
const ws = new WebSocket(wsUrl);
await new Promise((r) => ws.addEventListener("open", r));
let id = 0; const pend = new Map();
ws.addEventListener("message", (e) => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); } });
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const evalJs = async (expr) => (await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true })).result?.result?.value;
const mobile = Number(W) <= 900;
await send("Emulation.setDeviceMetricsOverride", { width: +W, height: +H, deviceScaleFactor: mobile ? 3 : 1, mobile });
if (mobile) await send("Emulation.setTouchEmulationEnabled", { enabled: true });
await send("Page.enable");
// record GA-ish events the app fires
await send("Page.addScriptToEvaluateOnNewDocument", { source: "window.__ev=[];window.gtag=function(){window.__ev.push([].slice.call(arguments));};" });
await send("Page.navigate", { url });
const MEASURE = `(() => {
  const vh = window.innerHeight, card = document.querySelector('#stories article.story');
  const panel = document.getElementById('panel'), map = document.getElementById('map'), hook = document.getElementById('welcomeHook');
  const r = (el) => el ? Math.round(el.getBoundingClientRect().top + window.scrollY) : null;
  const cr = card && card.getBoundingClientRect();
  return { scrollY: Math.round(window.scrollY), vh, cards: document.querySelectorAll('#stories article.story').length,
    ssr: !!document.querySelector('#stories [data-ssr]'),
    panelTopDoc: r(panel), mapTopDoc: r(map), mapH: map ? Math.round(map.getBoundingClientRect().height) : null,
    hookVisible: hook ? !hook.classList.contains('hidden') : null,
    firstCardTopDoc: r(card), firstCardTopView: cr ? Math.round(cr.top) : null,
    firstCardInView: cr ? (cr.top < vh && cr.bottom > 0) : false,
    scrollNeededToFirstCard: cr ? Math.max(0, Math.round(cr.top - vh + Math.min(cr.height, 80))) : null,
    title: (document.getElementById('panelTitle')||{}).textContent,
    events: (window.__ev||[]).filter(e => e[0]==='event').map(e => e[1]) };
})()`;
await sleep(+(process.env.WAIT || 6000));
const out = { url, W: +W, H: +H, onLoad: await evalJs(MEASURE) };
if (tap) {
  await evalJs(`(() => { window.scrollTo(0, 0); return true; })()`);
  // tap the country through the same path a map click uses
  const ok = await evalJs(`(() => { const i = document.getElementById('countrySearch'); if (!i) return false; i.value = ${JSON.stringify(tap)}; i.dispatchEvent(new Event('input', {bubbles:true})); i.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', bubbles:true})); i.blur(); return true; })()`);
  await sleep(4000);
  out.afterTap = { tapped: ok, ...(await evalJs(MEASURE)) };
}
if (process.env.SHOT) {
  const s = await send("Page.captureScreenshot", { format: "png" });
  (await import("node:fs")).writeFileSync(process.env.SHOT, Buffer.from(s.result.data, "base64"));
}
console.log(JSON.stringify(out, null, 1));
ws.close(); proc.kill();
process.exit(0);
