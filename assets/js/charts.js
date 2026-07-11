/* 纯 Canvas 图表库：温度仪表盘 / K线 / 折线 / 柱状（无第三方依赖） */
(function (global) {
  "use strict";

  var UP = "#f6465d", DOWN = "#2ebd85", DIM = "#9fb2cc", GRID = "#243a5e";

  function setup(canvas, h) {
    var dpr = window.devicePixelRatio || 1;
    var w = canvas.clientWidth || (canvas.parentElement && canvas.parentElement.clientWidth) || 600;
    canvas.width = Math.max(1, Math.floor(w * dpr));
    canvas.height = Math.max(1, Math.floor(h * dpr));
    var ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    return { ctx: ctx, w: w, h: h };
  }

  // 温度仪表盘（270° 弧）
  function gauge(canvas, val, level) {
    var s = setup(canvas, 200);
    var ctx = s.ctx, w = s.w, h = s.h, cx = w / 2, cy = h / 2, r = Math.min(w, h) / 2 - 14;
    var start = Math.PI * 0.75, end = Math.PI * 2.25;
    var color = level && (level.indexOf("热") >= 0 || level.indexOf("沸") >= 0) ? UP
      : (level && level.indexOf("温") >= 0 ? "#f0b90b" : "#2f81f7");
    // 底环
    ctx.lineWidth = 14; ctx.lineCap = "round";
    ctx.strokeStyle = GRID;
    ctx.beginPath(); ctx.arc(cx, cy, r, start, end); ctx.stroke();
    // 值环
    var frac = Math.max(0, Math.min(100, val)) / 100;
    ctx.strokeStyle = color;
    ctx.beginPath(); ctx.arc(cx, cy, r, start, start + (end - start) * frac); ctx.stroke();
  }

  // K线（蜡烛 + 成交量）
  function kline(canvas, bars, opts) {
    opts = opts || {};
    var n = bars.length;
    if (!n) return;
    var s = setup(canvas, 360);
    var ctx = s.ctx, w = s.w, h = s.h;
    var padL = 8, padR = 56, padT = 12, volH = 70, gap = 8;
    var priceH = h - padT - volH - gap - 18;
    var plotW = w - padL - padR;
    var lo = Infinity, hi = -Infinity, vmax = 0;
    bars.forEach(function (b) {
      lo = Math.min(lo, b.l); hi = Math.max(hi, b.h);
      vmax = Math.max(vmax, b.v || 0);
    });
    var pad = (hi - lo) * 0.06 || 1; lo -= pad; hi += pad;
    var step = plotW / n;
    var cw = Math.max(1.5, Math.min(14, step * 0.62));
    function y(v) { return padT + (hi - v) / (hi - lo) * priceH; }

    // 网格 + 价格刻度
    ctx.strokeStyle = GRID; ctx.lineWidth = 1; ctx.fillStyle = DIM; ctx.font = "11px sans-serif";
    for (var i = 0; i <= 4; i++) {
      var pv = hi - (hi - lo) * i / 4;
      var yy = y(pv);
      ctx.beginPath(); ctx.moveTo(padL, yy); ctx.lineTo(padL + plotW, yy); ctx.stroke();
      ctx.fillText(pv.toFixed(2), padL + plotW + 6, yy + 3);
    }

    // 蜡烛
    bars.forEach(function (b, i) {
      var x = padL + step * i + step / 2;
      var up = b.c >= b.o;
      var col = up ? UP : DOWN;
      ctx.strokeStyle = col; ctx.fillStyle = col;
      ctx.beginPath(); ctx.moveTo(x, y(b.h)); ctx.lineTo(x, y(b.l)); ctx.stroke();
      var yo = y(b.o), yc = y(b.c);
      var top = Math.min(yo, yc), bh = Math.max(1, Math.abs(yc - yo));
      ctx.fillRect(x - cw / 2, top, cw, bh);
      // 成交量
      var vh = vmax ? (b.v || 0) / vmax * (volH - 4) : 0;
      ctx.globalAlpha = 0.55;
      ctx.fillRect(x - cw / 2, h - 14 - vh, cw, vh);
      ctx.globalAlpha = 1;
    });
    // 成交量基线
    ctx.strokeStyle = GRID; ctx.beginPath();
    ctx.moveTo(padL, h - 14); ctx.lineTo(padL + plotW, h - 14); ctx.stroke();

    // 最新价线
    var last = bars[n - 1];
    ctx.strokeStyle = last.c >= last.o ? UP : DOWN; ctx.setLineDash([4, 3]);
    var ly = y(last.c);
    ctx.beginPath(); ctx.moveTo(padL, ly); ctx.lineTo(padL + plotW, ly); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = ctx.strokeStyle;
    ctx.fillRect(padL + plotW + 2, ly - 8, padR - 4, 16);
    ctx.fillStyle = "#fff"; ctx.fillText(last.c.toFixed(2), padL + plotW + 6, ly + 4);
  }

  // 折线 / 面积图
  function line(canvas, series, opts) {
    opts = opts || {};
    var s = setup(canvas, opts.height || 200);
    var ctx = s.ctx, w = s.w, h = s.h, padL = 40, padR = 12, padT = 12, padB = 22;
    if (!series || !series.length) return;
    var vals = series.map(function (p) { return p.v; });
    var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
    if (lo === hi) { hi += 1; lo -= 1; }
    var pad = (hi - lo) * 0.1; lo -= pad; hi += pad;
    var plotW = w - padL - padR, plotH = h - padT - padB;
    function X(i) { return padL + (series.length <= 1 ? plotW / 2 : plotW * i / (series.length - 1)); }
    function Y(v) { return padT + (hi - v) / (hi - lo) * plotH; }

    ctx.strokeStyle = GRID; ctx.fillStyle = DIM; ctx.font = "10px sans-serif"; ctx.lineWidth = 1;
    for (var i = 0; i <= 3; i++) {
      var gv = hi - (hi - lo) * i / 3, gy = Y(gv);
      ctx.beginPath(); ctx.moveTo(padL, gy); ctx.lineTo(padL + plotW, gy); ctx.stroke();
      ctx.fillText(gv.toFixed(0), 4, gy + 3);
    }
    // 面积
    var grad = ctx.createLinearGradient(0, padT, 0, padT + plotH);
    grad.addColorStop(0, "rgba(47,129,247,.35)");
    grad.addColorStop(1, "rgba(47,129,247,.02)");
    ctx.beginPath(); ctx.moveTo(X(0), Y(series[0].v));
    series.forEach(function (p, i) { ctx.lineTo(X(i), Y(p.v)); });
    if (series.length > 1) {
      ctx.lineTo(X(series.length - 1), padT + plotH); ctx.lineTo(X(0), padT + plotH);
    } else {
      ctx.lineTo(X(0), padT + plotH);
    }
    ctx.closePath(); ctx.fillStyle = grad; ctx.fill();
    // 线
    ctx.beginPath(); ctx.moveTo(X(0), Y(series[0].v));
    series.forEach(function (p, i) { ctx.lineTo(X(i), Y(p.v)); });
    ctx.strokeStyle = "#2f81f7"; ctx.lineWidth = 2; ctx.stroke();
    // x 轴标签（稀疏；单点时不除零）
    var labN = Math.min(6, series.length);
    for (var k = 0; k < labN; k++) {
      var idx = labN <= 1 ? 0 : Math.round(k * (series.length - 1) / (labN - 1));
      ctx.fillText(series[idx].l, X(idx) - 14, h - 6);
    }
  }

  // 柱状图
  function bars(canvas, items, opts) {
    opts = opts || {};
    var s = setup(canvas, opts.height || 200);
    var ctx = s.ctx, w = s.w, h = s.h, padL = 36, padR = 10, padT = 14, padB = 28;
    if (!items || !items.length) return;
    var vals = items.map(function (p) { return p.v; });
    var hi = Math.max.apply(null, vals), lo = Math.min.apply(null, vals);
    var maxAbs = Math.max(Math.abs(hi), Math.abs(lo)) || 1;
    var plotW = w - padL - padR, plotH = h - padT - padB;
    var bw = plotW / items.length * 0.62;
    ctx.font = "10px sans-serif";
    items.forEach(function (p, i) {
      var cx = padL + plotW * (i + 0.5) / items.length;
      var bh = Math.abs(p.v) / maxAbs * plotH;
      var col = p.color || (p.v >= 0 ? UP : DOWN);
      var yy = p.v >= 0 ? padT + (plotH - bh) : padT + plotH;
      ctx.fillStyle = col;
      ctx.fillRect(cx - bw / 2, yy, bw, bh);
      ctx.fillStyle = DIM;
      ctx.fillText(String(p.l), cx - bw / 2, h - 10);
    });
    // 零线
    ctx.strokeStyle = GRID; ctx.beginPath();
    ctx.moveTo(padL, padT + plotH); ctx.lineTo(padL + plotW, padT + plotH); ctx.stroke();
  }

  global.Charts = { gauge: gauge, kline: kline, line: line, bars: bars };
})(window);
