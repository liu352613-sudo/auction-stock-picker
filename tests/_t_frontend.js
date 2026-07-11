/* 前端校验（jsdom）：加载真实 index.html + assets/js，stub fetch，验证
   - 首页：数据日期/时效提示栏存在；卡片与表格含 data-f=score 与 data-f=delta；
     实时评分（/api/recommend 的 live_scores）能写入评分并打 delta 标记。
   - 详情页：8 维度评分拆解渲染（8 个 .sb-row + 风险调整条）。
   - 历史详情：展示「数据日期」。
   不依赖浏览器，纯本地校验渲染逻辑。 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("C:/Users/PC/.workbuddy/binaries/node/workspace/node_modules/jsdom");

const ROOT = "D:/auction-stock-picker";
const results = JSON.parse(fs.readFileSync(path.join(ROOT, "data/results.json"), "utf-8"));

function detailOf(s) { return s["评分明细"] || {}; }

function makeFetch() {
  return async function fetch(url) {
    const u = String(url);
    const resp = (obj) => ({ ok: true, status: 200, json: async () => obj });
    if (u.includes("results.json")) return resp(results);
    if (u.includes("/api/health")) return resp({ status: "ok" });
    if (u.includes("/api/market")) return resp({ indices: [], live: false });
    if (u.includes("/api/hot-sector")) return resp({ sectors: [] });
    if (u.includes("/api/recommend")) {
      const live_scores = {};
      (results.stocks || []).forEach((s) => {
        const d = detailOf(s);
        live_scores[s["代码"]] = {
          score: Number(s["评分"]) + 5.5, delta: 5.5,
          dimensions: d.dimensions || [],
          risk_factor: d.risk_factor || 1, risk_note: d.risk_note || "风险中性",
        };
      });
      return resp({
        trade_date: results.trade_date, effective_date: results.trade_date,
        data_freshness: "today", live_score_flag: true, live: null, live_flag: true,
        stocks: results.stocks, live_scores,
      });
    }
    if (u.includes("/api/stock/")) {
      const code = u.split("/api/stock/")[1];
      const s = (results.stocks || []).find((x) => x["代码"] === code);
      const d = s ? detailOf(s) : {};
      const live_score = s ? {
        score: Number(s["评分"]) - 3.3, delta: -3.3,
        dimensions: d.dimensions || [], risk_factor: d.risk_factor || 1, risk_note: d.risk_note || "风险中性",
      } : null;
      return resp({ code, live: null, live_flag: false, fund_flow: [], live_score, info: s, kline: { bars: [] } });
    }
    const fp = path.join(ROOT, u.replace(/^\//, ""));
    if (fs.existsSync(fp)) return resp(JSON.parse(fs.readFileSync(fp, "utf-8")));
    return { ok: false, status: 404, json: async () => ({}) };
  };
}

const html = fs.readFileSync(path.join(ROOT, "index.html"), "utf-8");
const dom = new JSDOM(html, { runScripts: "outside-only", url: "http://localhost/" });
const { window } = dom;
window.requestAnimationFrame = (cb) => setTimeout(cb, 0);
window.devicePixelRatio = 1;
window.fetch = makeFetch();
const ctxStub = new Proxy({}, { get: (t, p) => (p === "createLinearGradient" ? () => ({ addColorStop() {} }) : () => {}), set: () => true });
window.HTMLCanvasElement.prototype.getContext = () => ctxStub;

for (const f of ["assets/js/util.js", "assets/js/charts.js", "assets/js/app.js"]) {
  window.eval(fs.readFileSync(path.join(ROOT, f), "utf-8"));
}

let pass = 0, fail = 0;
function chk(name, cond, extra) {
  if (cond) { pass++; console.log("  [OK] " + name); }
  else { fail++; console.log("  [XX] " + name + "  " + (extra || "")); }
}
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  // ---- 首页 ----
  window.location.hash = "#/";
  window.dispatchEvent(new window.Event("hashchange"));
  await wait(250);
  const doc = window.document;
  const fb = doc.getElementById("freshness-bar");
  chk("首页 数据日期/时效栏存在", !!fb);
  chk("首页 时效栏含『数据日期』", fb && fb.textContent.indexOf("数据日期") >= 0, fb && fb.textContent);
  chk("首页 时效栏标注『今日实时推荐』(data_freshness=today)", fb && fb.textContent.indexOf("今日实时推荐") >= 0);

  const pickScore = doc.querySelector(".pick-card [data-f=\"score\"]");
  chk("精选卡 含 data-f=score", !!pickScore);
  chk("精选卡 含 data-f=delta", !!doc.querySelector(".pick-card [data-f=\"delta\"]"));
  const tblScore = doc.querySelector("tbody [data-f=\"score\"]");
  chk("表格 含 data-f=score", !!tblScore);

  const s0 = results.stocks[0];
  const expect = (Number(s0["评分"]) + 5.5).toFixed(1);
  chk("实时评分已写入卡片 (+" + 5.5 + ")", pickScore && pickScore.textContent === expect, pickScore && pickScore.textContent + " vs " + expect);
  const delta = doc.querySelector(".pick-card [data-f=\"delta\"]");
  chk("delta 标记已显示 ▲", delta && /▲/.test(delta.textContent), delta && delta.textContent);

  // ---- 详情页 ----
  window.location.hash = "#/detail/600519";
  window.dispatchEvent(new window.Event("hashchange"));
  await wait(250);
  const bd = doc.getElementById("score-breakdown");
  const rows = bd ? bd.querySelectorAll(".sb-row").length : 0;
  chk("详情 8 维度拆解渲染 (8 行)", rows === 8, "rows=" + rows);
  chk("详情 含风险调整条", bd && !!bd.querySelector(".sb-risk"));
  // 维度条分数与 max 比例合理（量比维度分数<=max）
  const firstFill = bd ? bd.querySelector(".sb-fill") : null;
  chk("维度条宽度样式存在", firstFill && /width:\s*[\d.]+%/.test(firstFill.getAttribute("style") || ""), firstFill && firstFill.getAttribute("style"));

  // ---- 历史详情 ----
  window.location.hash = "#/history/2026-07-10";
  window.dispatchEvent(new window.Event("hashchange"));
  await wait(250);
  const appText = doc.getElementById("app").textContent;
  chk("历史详情 展示『数据日期』", /数据日期/.test(appText));

  console.log("\n==== 前端校验 PASS=" + pass + " FAIL=" + fail + " ====");
  process.exit(fail ? 1 : 0);
})();
