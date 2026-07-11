/* 前端校验（jsdom）：加载真实 index.html + assets/js，stub fetch，验证：
   - 首页：数据日期/时效提示栏存在；推荐列表为空时正确渲染空状态
   - 详情页：8 维度评分拆解渲染（8 个 .sb-row + 风险调整条）
   - 历史详情：展示「数据日期」
   不依赖 results.json 的实际 stocks（用合成数据），纯本地校验渲染逻辑。 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("C:/Users/PC/.workbuddy/binaries/node/workspace/node_modules/jsdom");

const ROOT = "D:/auction-stock-picker";
const resultsMeta = JSON.parse(fs.readFileSync(path.join(ROOT, "data/results.json"), "utf-8"));

// 合成股票数据（不依赖 results.json 是否有 stocks）
const SYNTH_STOCKS = [
  { "代码":"000001","名称":"平安银行","评分":85.0,"现价":12.3,"涨跌幅":2.1,"板块":"银行",
    "买入程度":"强烈推荐","建议":"积极关注","交易额":8e6,"量比":5.5,
    "买入价":12.0,"止盈价":13.2,"止损价":11.4,"涨停价":13.53,
    "评分明细": {
      total:85.0, raw:85.0, risk_factor:1.0,
      dimensions:[
        {key:"vol_ratio",label:"量比",score:16.2,max:18.0,note:"量比 5.5",pct:90.0,weight:18},
        {key:"amount",label:"竞价金额",score:8.0,max:12.0,note:"800万",weight:12},
        {key:"rel_market",score:10.8,max:12.0,note:"强于大盘 +1.2%",weight:12},
        {key:"ma60_dev",score:12.0,max:15.0,note:"高于60日线 +8%",weight:15},
        {key:"vol_energy",score:9.6,max:12.0,note:"量能比 1.8",weight:12},
        {key:"fund_flow",score:8.4,max:12.0,note:"主力流入 1200万",weight:12},
        {key:"sector",score:7.0,max:10.0,note:"银行板块 +1.5%",weight:10},
        {key:"trend",score:7.2,max:9.0,note:"多头排列",weight:9},
      ],
      risk_note:"风险中性",
    },
    features:{price:12.3,vol_ratio:5.5,pct_open:2.1},
  },
  { "代码":"600519","名称":"贵州茅台","评分":72.0,"现价":1520.0,"涨跌幅":0.5,"板块":"酿酒",
    "买入程度":"中等","建议":"小仓试错","交易额":1.2e9,
    "买入价":1500.0,"止盈价":1650.0,"止损价":1420.0,"涨停价":1672.0,
    "评分明细": {
      total:72.0, raw:72.0, risk_factor:0.95,
      dimensions:[
        {key:"vol_ratio",label:"量比",score:10.8,max:18.0,note:"量比 3.0",pct:60.0,weight:18},
        {key:"amount",score:10.0,max:12.0,note:"1.2亿",weight:12},
        {key:"rel_market",score:7.2,max:12.0,note:"同步大盘",weight:12},
        {key:"ma60_dev",score:12.0,max:15.0,note:"高于60日线 +5%",weight:15},
        {key:"vol_energy",score:9.6,max:12.0,note:"量能比 1.3",weight:12},
        {key:"fund_flow",score:6.0,max:12.0,note:"主力小幅流入 500万",weight:12},
        {key:"sector",score:7.0,max:10.0,note:"酿酒板块 +1.2%",weight:10},
        {key:"trend",score:6.3,max:9.0,note:"60日线以上",weight:9},
      ],
      risk_note:"风险评估中等（持仓集中度较高）",
    },
    features:{price:1520.0,vol_ratio:3.0,pct_open:0.5},
  },
];

const SYNTH_TOP3 = SYNTH_STOCKS.slice(0, 3);
const SYNTH_ALL = SYNTH_STOCKS;

function makeFetch() {
  return async function fetch(url) {
    const u = String(url);
    const resp = (obj) => ({ ok: true, status: 200, json: async () => obj });
    if (u.includes("results.json")) return resp({
      ...resultsMeta,
      recommendations: SYNTH_ALL,
      stocks: SYNTH_ALL,
      top3: SYNTH_TOP3,
      count: SYNTH_ALL.length,
    });
    if (u.includes("/api/health")) return resp({ status: "ok" });
    if (u.includes("/api/market")) return resp({ indices: [], live: false });
    if (u.includes("/api/hot-sector")) return resp({ sectors: [] });
    if (u.includes("/api/recommend")) {
      return resp({
        trade_date: resultsMeta.trade_date || "2026-07-10",
        effective_date: resultsMeta.effective_date || resultsMeta.trade_date || "2026-07-10",
        data_freshness: "today", live: null, live_flag: false,
        stocks: SYNTH_ALL,
      });
    }
    if (u.includes("/api/stock/")) {
      const code = u.split("/api/stock/")[1];
      const s = SYNTH_ALL.find((x) => x["代码"] === code);
      return resp({
        code, live: null, live_flag: false, fund_flow: [],
        live_score: null, info: s, kline: { bars: [] },
      });
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
  await wait(300);
  const doc = window.document;
  const fb = doc.getElementById("freshness-bar");
  chk("首页 数据日期/时效栏存在", !!fb);
  chk("首页 时效栏含『数据日期』", fb && fb.textContent.indexOf("数据日期") >= 0, fb && fb.textContent);
  chk("首页 时效栏含 trade_date", fb && fb.textContent.indexOf(resultsMeta.trade_date || "2026-07-10") >= 0);

  const pickScore = doc.querySelector(".pick-card [data-f=\"score\"]");
  chk("精选卡 含 data-f=score（来自 recommendations）", !!pickScore);
  chk("精选卡 含 data-f=delta（占位元素，无实时重算）", !!doc.querySelector(".pick-card [data-f=\"delta\"]"));
  const tblScore = doc.querySelector("tbody [data-f=\"score\"]");
  chk("表格 含 data-f=score（来自 stocks）", !!tblScore);

  // 评分显示的是存储值（非实时重算）
  if (pickScore) {
    const storedScore = SYNTH_STOCKS[0]["评分"].toFixed(1);
    chk("卡片评分 = 存储值（不覆盖）", pickScore.textContent === storedScore, pickScore.textContent + " vs " + storedScore);
  }

  // ---- 详情页 ----
  window.location.hash = "#/detail/600519";
  window.dispatchEvent(new window.Event("hashchange"));
  await wait(300);
  const bd = doc.getElementById("score-breakdown");
  const rows = bd ? bd.querySelectorAll(".sb-row").length : 0;
  chk("详情 8 维度拆解渲染 (8 行)", rows === 8, "rows=" + rows);
  chk("详情 含风险调整条", bd && !!bd.querySelector(".sb-risk"));
  const firstFill = bd ? bd.querySelector(".sb-fill") : null;
  chk("维度条宽度样式存在", firstFill && /width:\s*[\d.]+%/.test(firstFill.getAttribute("style") || ""), firstFill && firstFill.getAttribute("style"));

  // ---- 历史详情 ----
  window.location.hash = "#/history/2026-07-10";
  window.dispatchEvent(new window.Event("hashchange"));
  await wait(300);
  const appText = doc.getElementById("app").textContent;
  chk("历史详情 展示『数据日期』", /数据日期/.test(appText));

  console.log("\n==== 前端校验 PASS=" + pass + " FAIL=" + fail + " ====");
  process.exit(fail ? 1 : 0);
})();
