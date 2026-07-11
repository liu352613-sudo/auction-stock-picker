/* 工具函数：DOM 创建、JSON 加载（带内存缓存）、格式化、配色 */
(function (global) {
  "use strict";

  // 简易 DOM 构建器：el('div', {class:'x'}, [child, '文本'])
  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        var v = attrs[k];
        if (k === "class") node.className = v;
        else if (k === "html") node.innerHTML = v;
        else if (k === "text") node.textContent = v;
        else if (k.slice(0, 2) === "on" && typeof v === "function") {
          node.addEventListener(k.slice(2), v);
        } else if (v !== null && v !== undefined && v !== false) {
          node.setAttribute(k, v);
        }
      });
    }
    if (children != null) {
      (Array.isArray(children) ? children : [children]).forEach(function (c) {
        if (c == null) return;
        node.appendChild(typeof c === "string" || typeof c === "number"
          ? document.createTextNode(String(c)) : c);
      });
    }
    return node;
  }

  // JSON 缓存（同一会话内不重复请求）
  var _cache = {};
  function fetchJSON(path, opts) {
    opts = opts || {};
    if (_cache[path] && !opts.noCache) return Promise.resolve(_cache[path]);
    return fetch(path, { cache: "no-cache" })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status + " " + path);
        return r.json();
      })
      .then(function (d) { _cache[path] = d; return d; });
  }

  function clearCache() { _cache = {}; }

  // ----------------------------------------------------------------------
  // 双模式：实时 API 层
  // API_BASE 默认同源（""）；若 API 独立部署，可在 index.html 设置
  //   <script>window.API_BASE = "https://api.your-domain.com";</script>
  // 前端「静态优先」：静态数据经 fetchJSON("data/...")，实时补充经 fetchAPI("/api/...")。
  // ----------------------------------------------------------------------
  var API_BASE = (typeof window !== "undefined" && window.API_BASE) ? window.API_BASE : "";

  // 调试验：关闭实时 API（离线单页预览时设为 false）
  var API_ENABLED = (typeof window !== "undefined" && window.API_ENABLED !== false);

  function fetchAPI(path, opts) {
    if (!API_ENABLED) return Promise.reject(new Error("API disabled"));
    opts = opts || {};
    var url = API_BASE + path;
    return fetch(url, { cache: "no-cache" })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      });
  }

  // 实时连接指示灯（header 中的 #live-indicator）
  function setLive(state, text) {
    var el = document.getElementById("live-indicator");
    if (!el) return;
    el.className = "live-ind " + (state || "");
    el.textContent = text || "";
  }

  // 涨跌配色（中国习惯：涨红跌绿）
  function pctClass(v) {
    if (v > 0) return "up";
    if (v < 0) return "down";
    return "flat";
  }
  function fmtPct(v) {
    if (v === null || v === undefined || isNaN(v)) return "-";
    return (v > 0 ? "+" : "") + v.toFixed(2) + "%";
  }
  function fmtNum(v, d) {
    d = d == null ? 2 : d;
    if (v === null || v === undefined || isNaN(v)) return "-";
    return Number(v).toLocaleString("zh-CN", { minimumFractionDigits: d, maximumFractionDigits: d });
  }
  function fmtMoney(v) {
    // 亿元
    if (v === null || v === undefined || isNaN(v)) return "-";
    if (v >= 10000) return (v / 10000).toFixed(2) + "万亿";
    return v.toFixed(2) + "亿";
  }

  function recoClass(deg) {
    if (deg === "强烈推荐") return "strong";
    if (deg === "中等") return "mid";
    if (deg === "谨慎" || deg === "不推荐") return "none";
    return "cautious";
  }

  function tempBadgeClass(level) {
    if (!level) return "";
    if (level.indexOf("热") >= 0 || level.indexOf("沸") >= 0) return "lv-hot";
    if (level.indexOf("温") >= 0) return "lv-warm";
    return "lv-cool";
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  global.U = {
    el: el, fetchJSON: fetchJSON, clearCache: clearCache,
    fetchAPI: fetchAPI, setLive: setLive, API_BASE: API_BASE, API_ENABLED: API_ENABLED,
    pctClass: pctClass, fmtPct: fmtPct, fmtNum: fmtNum, fmtMoney: fmtMoney,
    recoClass: recoClass, tempBadgeClass: tempBadgeClass, escapeHtml: escapeHtml,
  };
})(window);
