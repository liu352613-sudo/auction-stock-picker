/* 竞价选股 SPA：哈希路由 + 视图渲染（选股/详情/历史/收益/配置/优化） */
(function () {
  "use strict";
  var U = window.U, C = window.Charts;
  var app = document.getElementById("app");
  var nav = document.getElementById("nav");
  var dsBadge = document.getElementById("ds-badge");
  var footTime = document.getElementById("foot-time");

  // ---------- 路由 ----------
  function parseHash() {
    var h = location.hash.replace(/^#\/?/, ""); // 去掉 #/ 前缀
    var parts = h.split("/");
    var name = parts[0] || "pick";
    var param = parts[1] || null;
    return { name: name, param: param };
  }
  function setActive(route) {
    Array.prototype.forEach.call(nav.querySelectorAll(".nav-item"), function (a) {
      a.classList.toggle("active", a.getAttribute("data-route") === route);
    });
  }
  function go(hash) { location.hash = hash; }

  // ---------- 数据加载（带缓存） ----------
  function load(name) { return U.fetchJSON("data/" + name); }
  function loadKline(code) { return U.fetchJSON("data/klines/" + code + ".json"); }
  function loadSnapshot(date) { return U.fetchJSON("data/history/" + date + ".json"); }

  // ---------- 通用片段 ----------
  function setDS(res) {
    var live = res && (res.indices_live === true);
    var demo = res && /DEMO|样例|内置/i.test(res.data_source || "");
    dsBadge.className = "ds-badge " + (live ? "live" : (demo ? "demo" : ""));
    var label = live ? "实时行情" : (demo ? "内置样例数据" : "历史/缓存数据");
    dsBadge.textContent = label;
    if (footTime && res && res.generated_at) footTime.textContent = "更新于 " + res.generated_at;
  }

  function tempHero(temp) {
    var total = temp.total, level = temp.level || "";
    var canvas = U.el("canvas", { class: "gauge-canvas" });
    var center = U.el("div", { class: "gauge-center" }, [
      U.el("div", { class: "gauge-val", text: (total != null ? Number(total).toFixed(0) : "-") }),
      U.el("div", { class: "gauge-lvl " + U.tempBadgeClass(level), text: level }),
    ]);
    var gauge = U.el("div", { class: "gauge" }, [canvas, center]);
    var meta = U.el("div", { class: "hero-meta" }, [
      U.el("div", { class: "row" }, [
        U.el("span", { class: "muted small", text: "大盘温度反映市场集合竞价热度与赚钱效应" }),
      ]),
      U.el("div", { class: "row" }, [
        U.el("span", { class: "badge " + U.tempBadgeClass(level), text: level }),
        U.el("span", { class: "muted small", text: "建议仓位参考：" + (temp.position != null ? temp.position + "%" : "-") }),
      ]),
    ]);
    var card = U.el("div", { class: "card hero" }, [gauge, meta]);
    requestAnimationFrame(function () { C.gauge(canvas, Number(total) || 0, level); });
    return card;
  }

  function indicesGrid(indices, live) {
    var cards = (indices || []).map(function (ix) {
      var pct = parseFloat(String(ix.pct).replace("%", ""));
      return U.el("div", { class: "card index-card" }, [
        U.el("div", { class: "nm", text: ix.name }),
        U.el("div", { class: "vl", text: U.fmtNum(ix.val, 2) }),
        U.el("div", { class: "pc " + U.pctClass(pct), text: ix.pct }),
      ]);
    });
    return U.el("div", { class: "grid grid-5" }, cards);
  }

  function pickCard(s) {
    var pct = s["涨跌幅"] || 0;
    return U.el("div", { class: "card pick-card", onclick: function () { go("/detail/" + s["代码"]); } }, [
      U.el("div", { class: "top" }, [
        U.el("div", {}, [
          U.el("div", { class: "nm", text: s["名称"] }),
          U.el("div", { class: "cd", text: s["代码"] + " · " + (s["板块"] || "-") }),
        ]),
        U.el("div", { class: "score-ring " + (s["评分"] >= 80 ? "up" : (s["评分"] >= 60 ? "" : "down")), text: s["评分"].toFixed(1) }),
      ]),
      U.el("div", { class: "price" }, [
        U.el("span", { text: "现价 " + U.fmtNum(s["现价"], 2) }),
        U.el("span", { class: U.pctClass(pct), text: U.fmtPct(pct) }),
      ]),
      U.el("div", { class: "levels" }, [
        U.el("span", { class: "reco " + U.recoClass(s["买入程度"]), text: s["建议"] || s["买入程度"] }),
        U.el("span", { class: "muted small", text: "评分明细见详情" }),
      ]),
    ]);
  }

  function stocksTable(stocks, withDetail) {
    var head = U.el("thead", {}, U.el("tr", {}, [
      U.el("th", { class: "l", text: "排名" }),
      U.el("th", { class: "l", text: "名称/代码" }),
      U.el("th", { class: "l", text: "板块" }),
      U.el("th", { text: "现价" }),
      U.el("th", { text: "涨跌幅" }),
      U.el("th", { text: "评分" }),
      U.el("th", { text: "建议" }),
      U.el("th", { class: "l", text: "买入程度" }),
      withDetail ? U.el("th", { text: "操作" }) : null,
    ]));
    var rows = stocks.map(function (s) {
      var pct = s["涨跌幅"] || 0;
      return U.el("tr", {}, [
        U.el("td", { class: "l rank", text: "#" + s["排名"] }),
        U.el("td", { class: "l" }, [
          U.el("div", { class: "stk", text: s["名称"] }),
          U.el("small", { text: s["代码"] }),
        ]),
        U.el("td", { class: "l" }, [U.el("span", { class: "sector-tag", text: s["板块"] || "-" })]),
        U.el("td", { text: U.fmtNum(s["现价"], 2) }),
        U.el("td", { class: U.pctClass(pct), text: U.fmtPct(pct) }),
        U.el("td", { text: s["评分"].toFixed(1) }),
        U.el("td", {}, [U.el("span", { class: "reco " + U.recoClass(s["买入程度"]), text: s["建议"] || s["买入程度"] })]),
        U.el("td", { class: "l degree", text: s["买入程度"] || "-" }),
        withDetail ? U.el("td", {}, [U.el("button", { class: "btn-detail", onclick: function () { go("/detail/" + s["代码"]); } }, "详情")]) : null,
      ]);
    });
    return U.el("div", { class: "table-wrap" }, U.el("table", {}, [head, U.el("tbody", {}, rows)]));
  }

  // ---------- 视图：精选（选股主页） ----------
  function viewPick() {
    app.innerHTML = "";
    load("results.json").then(function (res) {
      setDS(res);
      var wrap = U.el("div", {});
      // 温度
      wrap.appendChild(U.el("div", { class: "section" }, [
        U.el("div", { class: "section-title", text: "大盘温度" }),
        tempHero(res.temperature || {}),
      ]));
      // 指数
      wrap.appendChild(U.el("div", { class: "section" }, [
        U.el("div", { class: "section-title", text: "实时指数" }),
        indicesGrid(res.indices, res.indices_live),
      ]));
      // Top3
      wrap.appendChild(U.el("div", { class: "section" }, [
        U.el("div", { class: "section-title", text: "今日精选 Top3" }),
        U.el("div", { class: "grid grid-3" }, (res.top3 || []).map(pickCard)),
      ]));
      // 全部
      wrap.appendChild(U.el("div", { class: "section" }, [
        U.el("div", { class: "section-title", text: "全部候选（" + (res.count || 0) + " 只）" }),
        stocksTable(res.stocks || [], true),
        U.el("div", { class: "note", text: "策略：集合竞价量比≥阈值 + 开盘涨幅动态区间 + 动能评分排序，T+1 次日开盘卖出。明细见个股详情。" }),
      ]));
      app.appendChild(wrap);
    }).catch(function (e) {
      app.innerHTML = '<div class="error">加载选股数据失败：' + U.escapeHtml(e.message) + '<br>请确认 data/results.json 已生成。</div>';
    });
  }

  // ---------- 视图：股票详情 + K线 ----------
  function viewDetail(code) {
    app.innerHTML = '<div class="loading">加载中…</div>';
    Promise.all([load("results.json"), loadKline(code)]).then(function (rs) {
      var res = rs[0], kline = rs[1];
      var stock = (res.stocks || []).filter(function (s) { return s["代码"] === code; })[0]
        || (res.top3 || []).filter(function (s) { return s["代码"] === code; })[0];
      renderDetail(code, stock, kline);
    }).catch(function (e) {
      app.innerHTML = '<div class="error">加载详情失败：' + U.escapeHtml(e.message) + '</div>';
    });
  }

  function renderDetail(code, stock, kline) {
    app.innerHTML = "";
    var name = stock ? stock["名称"] : code;
    var head = U.el("div", { class: "detail-head" }, [
      U.el("span", { class: "nm", text: name }),
      U.el("span", { class: "cd", text: code }),
      stock ? U.el("span", { class: "sector-tag", text: stock["板块"] || "-" }) : null,
      U.el("span", { class: "muted small", text: "返回" , onclick: function(){ go("/"); }, style: "cursor:pointer;text-decoration:underline;" }),
    ]);

    // 关键指标
    var statsData = [];
    if (stock) {
      statsData = [
        ["现价", U.fmtNum(stock["现价"], 2)],
        ["涨跌幅", U.fmtPct(stock["涨跌幅"] || 0)],
        ["动能评分", stock["评分"].toFixed(1)],
        ["建议", stock["建议"] || stock["买入程度"]],
        ["买入价", U.fmtNum(stock["买入价"], 2)],
        ["止盈价", U.fmtNum(stock["止盈价"], 2)],
        ["止损价", U.fmtNum(stock["止损价"], 2)],
        ["涨停价", U.fmtNum(stock["涨停价"], 2)],
        ["市值", U.fmtMoney(stock["市值"])],
        ["量比", U.fmtNum(stock["量比"], 2)],
      ];
    }
    var statsRow = U.el("div", { class: "detail-stats" },
      statsData.map(function (kv) {
        return U.el("div", { class: "stat" }, [
          U.el("div", { class: "k", text: kv[0] }),
          U.el("div", { class: "v " + (kv[0] === "涨跌幅" ? U.pctClass(stock["涨跌幅"] || 0) : ""), text: kv[1] }),
        ]);
      }));

    // 评分明细
    var detailNode = null;
    if (stock && stock["评分明细"]) {
      var d = stock["评分明细"];
      var items = [
        ["量比分", d["量比分"]], ["相对大盘分", d["相对大盘分"]],
        ["均线偏离分", d["均线偏离分"]], ["量能比分", d["量能比分"]],
        ["偏离度%", d["偏离度%"]], ["量能比%", d["量能比%"]],
      ];
      detailNode = U.el("div", { class: "section" }, [
        U.el("div", { class: "section-title", text: "评分明细" }),
        U.el("div", { class: "grid grid-3" }, items.map(function (it) {
          return U.el("div", { class: "stat" }, [
            U.el("div", { class: "k", text: it[0] }),
            U.el("div", { class: "v", text: it[1] != null ? it[1] : "-" }),
          ]);
        })),
      ]);
    }

    // K线
    var canvas = U.el("canvas", {});
    var ranges = [["近30日", 30], ["近60日", 60], ["全部", 9999]];
    var tabs = U.el("div", { class: "range-tabs" }, ranges.map(function (r, i) {
      return U.el("button", {
        class: i === ranges.length - 1 ? "active" : "",
        text: r[0],
        "data-n": r[1],
        onclick: function () {
          Array.prototype.forEach.call(tabs.children, function (b) { b.classList.remove("active"); });
          this.classList.add("active");
          drawK(code, kline, Number(this.getAttribute("data-n")), canvas);
        },
      });
    }));
    var kbox = U.el("div", { class: "kline-box" }, [tabs, canvas]);

    var wrap = U.el("div", {});
    wrap.appendChild(U.el("div", { class: "section" }, head));
    if (stock) wrap.appendChild(U.el("div", { class: "section" }, statsRow));
    if (detailNode) wrap.appendChild(detailNode);
    wrap.appendChild(U.el("div", { class: "section" }, [
      U.el("div", { class: "section-title", text: "K线走势" }),
      kbox,
      U.el("div", { class: "note", text: "红涨绿跌（中国习惯）。数据为演示/历史区间，仅供研究。" }),
    ]));
    app.appendChild(wrap);
    drawK(code, kline, 9999, canvas);
  }

  function drawK(code, kline, n, canvas) {
    if (!kline || !kline.bars || !kline.bars.length) {
      canvas.parentNode.appendChild(U.el("div", { class: "empty", text: "暂无 K 线数据" }));
      return;
    }
    var bars = kline.bars.slice(-n);
    requestAnimationFrame(function () { C.kline(canvas, bars); });
  }

  // ---------- 视图：历史推荐 ----------
  function viewHistory() {
    app.innerHTML = '<div class="loading">加载中…</div>';
    load("history_index.json").then(function (idx) {
      app.innerHTML = "";
      if (!idx || !idx.length) {
        app.appendChild(U.el("div", { class: "empty", text: "暂无历史推荐记录。运行 generate_snapshot.py 或每日定时任务后将在此累积。" }));
        return;
      }
      var list = U.el("div", { class: "list" }, idx.map(function (e) {
        return U.el("div", { class: "list-item", onclick: function () { go("/history/" + e.date); } }, [
          U.el("div", { class: "date", text: e.date }),
          U.el("div", { class: "pill" }, [U.el("span", { class: "badge " + U.tempBadgeClass(e.level), text: e.level || "-" })]),
          U.el("div", { class: "meta", text: e.count + " 只 · 平均评分 " + (e.avg_score != null ? e.avg_score : "-") + " · Top1 " + (e.top1 || "-") + " (" + (e.top1_code || "-") + ")" }),
          U.el("div", { class: "muted small", text: e.data_source || "" }),
          U.el("div", { class: "arrow", text: "›" }),
        ]);
      }));
      app.appendChild(U.el("div", { class: "section" }, [
        U.el("div", { class: "section-title", text: "历史推荐（" + idx.length + " 期）" }),
        list,
        U.el("div", { class: "note", text: "每日生成 results.json 后由 generate_snapshot.py 存档为 data/history/YYYY-MM-DD.json。" }),
      ]));
    }).catch(function (e) {
      app.innerHTML = '<div class="error">加载历史失败：' + U.escapeHtml(e.message) + '</div>';
    });
  }

  function viewHistoryDetail(date) {
    app.innerHTML = '<div class="loading">加载中…</div>';
    loadSnapshot(date).then(function (snap) {
      app.innerHTML = "";
      var temp = snap.temperature || {};
      var wrap = U.el("div", {});
      wrap.appendChild(U.el("div", { class: "section" }, [
        U.el("div", { class: "section-title", text: "历史推荐 · " + date }),
        U.el("div", { class: "grid grid-3" }, [
          U.el("div", { class: "stat" }, [U.el("div", { class: "k", text: "大盘温度" }), U.el("div", { class: "v", text: (temp.total != null ? temp.total : "-") + " (" + (temp.level || "-") + ")" })]),
          U.el("div", { class: "stat" }, [U.el("div", { class: "k", text: "推荐数" }), U.el("div", { class: "v", text: snap.count != null ? snap.count : (snap.stocks || []).length })]),
          U.el("div", { class: "stat" }, [U.el("div", { class: "k", text: "参数已调优" }), U.el("div", { class: "v", text: snap.params_tuned ? "是" : "否" })]),
        ]),
      ]));
      wrap.appendChild(U.el("div", { class: "section" }, [
        U.el("div", { class: "section-title", text: "当日候选" }),
        stocksTable(snap.stocks || [], false),
      ]));
      if (snap.indices) wrap.appendChild(U.el("div", { class: "section" }, [
        U.el("div", { class: "section-title", text: "当日指数" }),
        indicesGrid(snap.indices, false),
      ]));
      wrap.appendChild(U.el("div", { class: "note", text: "数据源：" + (snap.data_source || "-") + " · 快照时间：" + (snap.snapshot_at || "-") }));
      app.appendChild(wrap);
    }).catch(function (e) {
      app.innerHTML = '<div class="error">加载 ' + U.escapeHtml(date) + ' 失败：' + U.escapeHtml(e.message) + '</div>';
    });
  }

  // ---------- 视图：收益统计 ----------
  function viewStats() {
    app.innerHTML = '<div class="loading">加载中…</div>';
    load("stats.json").then(function (s) {
      app.innerHTML = "";
      var wrap = U.el("div", {});

      // 回测 KPI
      var bt = s.backtest || {};
      var prim = bt.primary;
      if (prim) {
        var st = prim.stats || {};
        var kpis = [
          ["胜率%", U.fmtNum(st["胜率%"], 2) + "%", ""],
          ["累计收益%(复利)", U.fmtPct(st["累计收益%(复利)"]), U.pctClass(st["累计收益%(复利)"])],
          ["平均收益率%", U.fmtPct(st["平均收益率%"]), U.pctClass(st["平均收益率%"])],
          ["最大单笔亏损%", U.fmtPct(st["最大单笔亏损%"]), "down"],
        ];
        wrap.appendChild(U.el("div", { class: "section" }, [
          U.el("div", { class: "section-title", text: "回测绩效（" + prim.period + " · " + (prim.data_source || "") + "）" }),
          U.el("div", { class: "kpi-row" }, kpis.map(function (k) {
            return U.el("div", { class: "kpi" }, [
              U.el("div", { class: "v " + k[2], text: k[1] }),
              U.el("div", { class: "k", text: k[0] }),
            ]);
          })),
          U.el("div", { class: "note", text: "退出规则：" + (prim.exit_rule || "T+1 次日开盘卖出") + "。样本 " + U.fmtNum(st["交易次数"], 0) + " 笔，触达+5% " + U.fmtNum(st["触达+5%次数"], 0) + " 次 / 触达-3% " + U.fmtNum(st["触达-3%次数"], 0) + " 次。" }),
        ]));
        // 月度分解
        if (prim.monthly && prim.monthly.length) {
          var mcanvas = U.el("canvas", {});
          wrap.appendChild(U.el("div", { class: "section" }, [
            U.el("div", { class: "section-title", text: "月度收益分解" }),
            U.el("div", { class: "chart-box" }, [U.el("div", { class: "chart-title", text: "各月累计收益%（等权）" }), mcanvas]),
          ]));
          requestAnimationFrame(function () {
            C.bars(mcanvas, prim.monthly.map(function (m) {
              return { l: m.month.slice(2), v: m.cum_return, color: m.cum_return >= 0 ? "#f6465d" : "#2ebd85" };
            }), { height: 200 });
          });
        }
      } else {
        wrap.appendChild(U.el("div", { class: "empty", text: "暂无回测绩效数据。运行 auto_tune.py / run_backtest 生成回测报告后展示。" }));
      }

      // 推荐活跃度
      var rec = s.recommendation || {};
      if (rec && rec.total_days) {
        var rkpis = [
          ["推荐天数", rec.total_days, ""],
          ["累计推荐", rec.total_picks, ""],
          ["平均评分", rec.avg_score, ""],
          ["平均温度", rec.avg_temperature, ""],
        ];
        wrap.appendChild(U.el("div", { class: "section" }, [
          U.el("div", { class: "section-title", text: "推荐活跃度" }),
          U.el("div", { class: "kpi-row" }, rkpis.map(function (k) {
            return U.el("div", { class: "kpi" }, [
              U.el("div", { class: "v", text: k[1] }),
              U.el("div", { class: "k", text: k[0] }),
            ]);
          })),
        ]));
        // 评分分布
        var sd = rec.score_distribution || {};
        var scanvas = U.el("canvas", {});
        wrap.appendChild(U.el("div", { class: "section" }, [
          U.el("div", { class: "section-title", text: "评分分布" }),
          U.el("div", { class: "chart-box" }, [U.el("div", { class: "chart-title", text: "各评分区间候选数" }), scanvas]),
        ]));
        requestAnimationFrame(function () {
          C.bars(scanvas, Object.keys(sd).map(function (k) {
            return { l: k, v: sd[k], color: "#2f81f7" };
          }), { height: 200 });
        });
        // 高频个股
        if (rec.top_picks && rec.top_picks.length) {
          var tp = U.el("div", { class: "list" }, rec.top_picks.map(function (p) {
            return U.el("div", { class: "list-item", onclick: function () { go("/detail/" + p.code); } }, [
              U.el("div", { class: "date", text: p.name }),
              U.el("div", { class: "meta", text: p.code + " · 出现 " + p.count + " 次 · 平均评分 " + p.avg_score }),
              U.el("div", { class: "arrow", text: "›" }),
            ]);
          }));
          wrap.appendChild(U.el("div", { class: "section" }, [
            U.el("div", { class: "section-title", text: "高频推荐个股" }),
            tp,
          ]));
        }
        // 趋势
        if (rec.trend && rec.trend.length) {
          var tcanvas = U.el("canvas", {});
          wrap.appendChild(U.el("div", { class: "section" }, [
            U.el("div", { class: "section-title", text: "评分/温度趋势" }),
            U.el("div", { class: "chart-box" }, [U.el("div", { class: "chart-title", text: "每日平均评分 与 温度" }), tcanvas]),
          ]));
          requestAnimationFrame(function () {
            C.line(tcanvas, rec.trend.map(function (t) {
              return { l: t.date ? t.date.slice(5) : "", v: t.avg_score };
            }), { height: 200 });
          });
        }
      }

      // 调参摘要
      var tu = s.tuning;
      if (tu && tu.best_params) {
        wrap.appendChild(U.el("div", { class: "section" }, [
          U.el("div", { class: "section-title", text: "策略调参摘要" }),
          U.el("div", { class: "stat", html: "<div class='k'>最优参数组合（共 " + (tu.n_combos || 0) + " 组网格搜索）</div>" +
            "<div class='v' style='font-size:14px;font-weight:600'>" + Object.keys(tu.best_params).map(function (k) {
              return k + "=" + tu.best_params[k];
            }).join("，") + "</div>" }),
          U.el("div", { class: "note", text: "查看完整灵敏度表与对比请前往「策略优化」。" }),
        ]));
      }

      app.appendChild(wrap);
    }).catch(function (e) {
      app.innerHTML = '<div class="error">加载收益统计失败：' + U.escapeHtml(e.message) + '</div>';
    });
  }

  // ---------- 视图：参数配置 ----------
  var PARAM_SCHEMA = [
    { g: "初筛", k: "vol_ratio_min", l: "量比下限", t: "number", step: 0.1, hint: "集合竞价量比阈值" },
    { g: "初筛", k: "auction_amount_min", l: "竞价成交额下限(元)", t: "number", step: 100000, hint: "低于此金额剔除" },
    { g: "初筛", k: "new_stock_days", l: "次新过滤天数", t: "number", step: 1, hint: "上市不足则剔除" },
    { g: "初筛", k: "threshold_lo_base", l: "开盘涨幅下限%", t: "number", step: 0.1 },
    { g: "初筛", k: "threshold_hi_base", l: "开盘涨幅上限%", t: "number", step: 0.1 },
    { g: "初筛", k: "threshold_lo_offset", l: "涨幅下限偏移%", t: "number", step: 0.1 },
    { g: "初筛", k: "threshold_hi_offset", l: "涨幅上限偏移%", t: "number", step: 0.1 },
    { g: "风控", k: "take_profit", l: "止盈%", t: "number", step: 0.01 },
    { g: "风控", k: "stop_loss", l: "止损%", t: "number", step: 0.01 },
    { g: "风控", k: "filter_st", l: "剔除ST", t: "switch" },
    { g: "风控", k: "filter_new_stock", l: "剔除次新", t: "switch" },
    { g: "风控", k: "filter_suspended", l: "剔除停牌", t: "switch" },
    { g: "风控", k: "filter_limit_up", l: "剔除涨停", t: "switch" },
    { g: "评分权重", k: "w_vol_ratio", l: "量比权重", t: "number", step: 1 },
    { g: "评分权重", k: "w_rel_market", l: "相对大盘权重", t: "number", step: 1 },
    { g: "评分权重", k: "w_ma60_dev", l: "均线偏离权重", t: "number", step: 1 },
    { g: "评分权重", k: "w_vol_energy", l: "量能比权重", t: "number", step: 1 },
    { g: "评分权重", k: "sector_bonus", l: "板块加成", t: "number", step: 0.5 },
    { g: "评分权重", k: "vol_ratio_top", l: "量比封顶", t: "number", step: 0.1 },
    { g: "评分权重", k: "ma60_dev_sweet", l: "均线偏离甜区%", t: "number", step: 0.01 },
    { g: "评分权重", k: "ma60_dev_max", l: "均线偏离上限%", t: "number", step: 0.01 },
    { g: "评分权重", k: "vol_energy_lo", l: "量能比下限%", t: "number", step: 0.01 },
    { g: "评分权重", k: "vol_energy_hi", l: "量能比上限%", t: "number", step: 0.01 },
    { g: "买入程度", k: "level_strong", l: "强烈推荐分数线", t: "number", step: 1 },
    { g: "买入程度", k: "level_mid", l: "中等分数线", t: "number", step: 1 },
    { g: "买入程度", k: "level_cautious", l: "谨慎分数线", t: "number", step: 1 },
  ];
  var LS_KEY = "asp_params_override";

  function viewConfig() {
    app.innerHTML = '<div class="loading">加载中…</div>';
    load("params.json").then(function (p) {
      app.innerHTML = "";
      var applied = (p.best && (JSON.stringify(p.best) !== JSON.stringify(p.default))) ? p.best : p.default;
      var override = {};
      try { override = JSON.parse(localStorage.getItem(LS_KEY) || "{}"); } catch (e) {}
      var values = Object.assign({}, applied, override);

      var groups = {};
      PARAM_SCHEMA.forEach(function (f) { (groups[f.g] = groups[f.g] || []).push(f); });
      var formGrid = U.el("div", { class: "form-grid" });
      Object.keys(groups).forEach(function (g) {
        var gcard = U.el("div", { class: "card" }, [U.el("h3", { text: g })]);
        groups[g].forEach(function (f) {
          if (f.t === "switch") {
            var inp = U.el("input", { type: "checkbox", "data-k": f.k });
            inp.checked = !!values[f.k];
            gcard.appendChild(U.el("div", { class: "field switch" }, [
              U.el("label", { text: f.l }), inp,
            ]));
          } else {
            gcard.appendChild(U.el("div", { class: "field" }, [
              U.el("label", { text: f.l }),
              U.el("input", { type: "number", step: f.step, value: values[f.k], "data-k": f.k }),
              f.hint ? U.el("span", { class: "hint", text: f.hint }) : null,
            ]));
          }
        });
        formGrid.appendChild(gcard);
      });

      function collect() {
        var o = {};
        Array.prototype.forEach.call(formGrid.querySelectorAll("[data-k]"), function (inp) {
          var k = inp.getAttribute("data-k");
          if (inp.type === "checkbox") o[k] = inp.checked;
          else o[k] = parseFloat(inp.value);
        });
        return o;
      }
      function download(name, obj) {
        var blob = new Blob([JSON.stringify(obj, null, 2)], { type: "application/json" });
        var a = document.createElement("a");
        a.href = URL.createObjectURL(blob); a.download = name; a.click();
        setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
      }

      var actions = U.el("div", { class: "form-actions" }, [
        U.el("button", { class: "btn primary", text: "保存到本地", onclick: function () {
          localStorage.setItem(LS_KEY, JSON.stringify(collect()));
          alert("已保存到浏览器本地（localStorage）。\n本地改动仅影响本机预览；正式生效需在 CI/本机重新运行 generate_results.py 与 auto_tune.py。");
        } }),
        U.el("button", { class: "btn", text: "导出参数JSON", onclick: function () {
          download("strategy_params.json", collect());
        } }),
        U.el("button", { class: "btn", text: "重置本地", onclick: function () {
          localStorage.removeItem(LS_KEY); location.reload();
        } }),
      ]);

      var wrap = U.el("div", {});
      wrap.appendChild(U.el("div", { class: "section" }, [
        U.el("div", { class: "section-title", text: "参数配置" }),
        U.el("div", { class: "note", html: "当前线上生效参数（best）：" + Object.keys(applied).map(function (k) { return k + "=" + applied[k]; }).join("，") }),
        U.el("div", { class: "note", text: "调优时间：" + (p.tuned_at || "出厂默认（未运行自动调参）") + (override && Object.keys(override).length ? "  · 本机有本地覆盖项" : "") }),
      ]));
      wrap.appendChild(U.el("div", { class: "section" }, [
        U.el("div", { class: "section-title", text: "策略参数" }),
        formGrid, actions,
        U.el("div", { class: "note", text: "说明：本页为静态站点，参数修改保存在浏览器本地。生产环境通过 build 流程（generate_results.py / auto_tune.py）读取 data/params.json 生效，并提交更新。" }),
      ]));
      app.appendChild(wrap);
    }).catch(function (e) {
      app.innerHTML = '<div class="error">加载参数失败：' + U.escapeHtml(e.message) + '</div>';
    });
  }

  // ---------- 视图：策略优化 ----------
  function viewOptimize() {
    app.innerHTML = '<div class="loading">加载中…</div>';
    load("param_tuning.json").then(function (pt) {
      app.innerHTML = "";
      var results = (pt.results || []).slice().sort(function (a, b) { return b.objective - a.objective; });
      var wrap = U.el("div", {});
      // 概要
      wrap.appendChild(U.el("div", { class: "section" }, [
        U.el("div", { class: "section-title", text: "策略优化（网格搜索）" }),
        U.el("div", { class: "note", text: "在 " + (pt.meta && pt.meta.grid_keys ? pt.meta.grid_keys.join(" / ") : "多参数") + " 空间搜索，目标函数 = 收益×胜率×样本量因子 − 风险惩罚。共 " + results.length + " 组，区间 " + (pt.meta ? (pt.meta.start + "~" + pt.meta.end) : "-") + "。" }),
      ]));
      // 目标函数对比
      if (results.length) {
        var ocanvas = U.el("canvas", {});
        wrap.appendChild(U.el("div", { class: "section" }, [
          U.el("div", { class: "section-title", text: "各组合目标函数得分" }),
          U.el("div", { class: "chart-box" }, [U.el("div", { class: "chart-title", text: "objective（越高越优，n<5 已惩罚）" }), ocanvas]),
        ]));
        requestAnimationFrame(function () {
          C.bars(ocanvas, results.map(function (r, i) {
            return { l: "#" + (i + 1), v: r.objective, color: r.objective >= 0 ? "#f6465d" : "#2ebd85" };
          }), { height: 220 });
        });
      }
      // 明细表
      var head = U.el("thead", {}, U.el("tr", {}, [
        U.el("th", { class: "l", text: "排名" }),
        U.el("th", { class: "l", text: "参数组合" }),
        U.el("th", { text: "交易次数" }),
        U.el("th", { text: "胜率%" }),
        U.el("th", { text: "累计收益%(复利)" }),
        U.el("th", { text: "目标" }),
      ]));
      var rows = results.map(function (r, i) {
        var combo = r.combo || {};
        return U.el("tr", {}, [
          U.el("td", { class: "l rank", text: "#" + (i + 1) }),
          U.el("td", { class: "l", text: Object.keys(combo).map(function (k) { return k + "=" + combo[k]; }).join("，") }),
          U.el("td", { text: (r.stats && r.stats["交易次数"] != null) ? r.stats["交易次数"] : "-" }),
          U.el("td", { text: (r.stats && r.stats["胜率%"] != null) ? r.stats["胜率%"] : "-" }),
          U.el("td", { class: U.pctClass((r.stats && r.stats["累计收益%(复利)"]) || 0), text: (r.stats && r.stats["累计收益%(复利)"] != null) ? U.fmtPct(r.stats["累计收益%(复利)"]) : "-" }),
          U.el("td", { text: (r.objective != null ? r.objective : "-") }),
        ]);
      });
      wrap.appendChild(U.el("div", { class: "section" }, [
        U.el("div", { class: "section-title", text: "参数-绩效灵敏度表" }),
        U.el("div", { class: "table-wrap" }, U.el("table", {}, [head, U.el("tbody", {}, rows)])),
      ]));
      app.appendChild(wrap);
    }).catch(function (e) {
      app.innerHTML = '<div class="error">加载调参结果失败：' + U.escapeHtml(e.message) + '</div>';
    });
  }

  // ---------- 路由分发 ----------
  function render() {
    var r = parseHash();
    setActive(r.name === "history" && r.param ? "history" : r.name);
    app.scrollTop = 0;
    switch (r.name) {
      case "pick": viewPick(); break;
      case "detail": viewDetail(r.param); break;
      case "history":
        if (r.param) viewHistoryDetail(r.param); else viewHistory();
        break;
      case "stats": viewStats(); break;
      case "config": viewConfig(); break;
      case "optimize": viewOptimize(); break;
      default: viewPick();
    }
  }

  window.addEventListener("hashchange", render);
  render();
})();
