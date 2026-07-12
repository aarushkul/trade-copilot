/* Trade Copilot dashboard. Push-only WebSocket client. */
(function () {
  "use strict";

  // ---------- chart ----------
  const chartEl = document.getElementById("chart");
  // Render all chart times in ET (the tape's clock); the library defaults to UTC.
  const etTime = (ts) => new Date(ts * 1000).toLocaleTimeString("en-US",
    { timeZone: "America/New_York", hour12: false, hour: "2-digit", minute: "2-digit" });
  const chart = LightweightCharts.createChart(chartEl, {
    layout: { background: { color: "#0d1117" }, textColor: "#8b949e" },
    grid: {
      vertLines: { color: "rgba(45,51,59,0.4)" },
      horzLines: { color: "rgba(45,51,59,0.4)" },
    },
    timeScale: {
      timeVisible: true, secondsVisible: false, borderColor: "#2d333b",
      tickMarkFormatter: (ts, type) => type >= 3 ? etTime(ts)
        : new Date(ts * 1000).toLocaleDateString("en-US",
          { timeZone: "America/New_York", month: "short", day: "numeric" }),
    },
    localization: { timeFormatter: (ts) => etTime(ts) + " ET" },
    rightPriceScale: { borderColor: "#2d333b" },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
  });
  const candles = chart.addCandlestickSeries({
    upColor: "#2ea44f", downColor: "#da3633",
    wickUpColor: "#3fb950", wickDownColor: "#f85149",
    borderVisible: false,
  });
  new ResizeObserver(() => {
    chart.applyOptions({ width: chartEl.clientWidth, height: chartEl.clientHeight });
  }).observe(chartEl);

  const priceLines = {};        // name -> IPriceLine
  function setLine(name, value, color, style, title) {
    if (value == null) {
      if (priceLines[name]) { candles.removePriceLine(priceLines[name]); delete priceLines[name]; }
      return;
    }
    if (priceLines[name]) {
      priceLines[name].applyOptions({ price: value });
    } else {
      priceLines[name] = candles.createPriceLine({
        price: value, color: color, lineWidth: 1,
        lineStyle: style, axisLabelVisible: true, title: title || name,
      });
    }
  }

  let signalLines = [];
  function drawSignalLines(sig) {
    signalLines.forEach((l) => candles.removePriceLine(l));
    signalLines = [];
    if (!sig) return;
    const mk = (price, color, title) => {
      signalLines.push(candles.createPriceLine({
        price: price, color: color, lineWidth: 2,
        lineStyle: LightweightCharts.LineStyle.Solid, axisLabelVisible: true, title: title,
      }));
    };
    mk(sig.entry, "#388bfd", "ENTRY");
    mk(sig.stop, "#f85149", "STOP");
    mk(sig.target1, "#3fb950", "T1");
    mk(sig.target2, "#2ea44f", "T2");
  }

  // ---------- sound ----------
  let audioCtx = null;
  function chime(kind) {
    if (!settings.sound_enabled) return;
    try {
      audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
      const seq = kind === "signal" ? [880, 1174.7, 1568]
        : kind === "win" ? [1046.5, 1568] : [392, 261.6];
      seq.forEach((f, i) => {
        const o = audioCtx.createOscillator();
        const g = audioCtx.createGain();
        o.frequency.value = f;
        o.type = "sine";
        g.gain.setValueAtTime(0.001, audioCtx.currentTime + i * 0.15);
        g.gain.exponentialRampToValueAtTime(0.25, audioCtx.currentTime + i * 0.15 + 0.03);
        g.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + i * 0.15 + 0.35);
        o.connect(g).connect(audioCtx.destination);
        o.start(audioCtx.currentTime + i * 0.15);
        o.stop(audioCtx.currentTime + i * 0.15 + 0.4);
      });
    } catch (e) { /* audio blocked until first user interaction; fine */ }
  }

  // ---------- dom helpers ----------
  const $ = (id) => document.getElementById(id);
  const fmt = (v, d = 2) => (v == null ? "—" : Number(v).toFixed(d));
  const fmtMoney = (v) => (v == null ? "—" : (v < 0 ? "-$" : "$") + Math.abs(v).toFixed(0));

  // ---------- state ----------
  let settings = {};
  let lastPrice = null;
  let activeSignal = null;
  let ttlTimer = null;
  let lastBarTime = 0;

  // lightweight-charts throws (and blanks the series) on non-ascending
  // times, so sanitize snapshots and drop stale updates instead of crashing.
  function setChartData(bars) {
    const clean = [];
    bars.slice().sort((a, b) => a.time - b.time).forEach((b) => {
      if (clean.length && clean[clean.length - 1].time === b.time) {
        clean[clean.length - 1] = b;         // keep the freshest duplicate
      } else {
        clean.push(b);
      }
    });
    candles.setData(clean);
    lastBarTime = clean.length ? clean[clean.length - 1].time : 0;
  }

  function updateChartBar(bar) {
    if (bar.time < lastBarTime) return;      // stale/out-of-order: ignore
    candles.update(bar);
    lastBarTime = bar.time;
  }

  function setSignalCard(sig, standAsideReason) {
    const card = $("signal-card");
    const body = $("sc-body");
    if (sig && (sig.status === "OPEN" || sig.status === "ACTIVE")) {
      card.className = sig.direction === "LONG" ? "long" : "short";
      $("sc-status").textContent =
        sig.direction + "  ·  " + sig.grade + "-grade  ·  score " + sig.score;
      $("sc-reason").textContent = "setup: " + sig.setup_type;
      body.classList.remove("hidden");
      $("sc-entry").textContent = fmt(sig.entry);
      $("sc-stop").textContent = fmt(sig.stop);
      $("sc-t1").textContent = fmt(sig.target1);
      $("sc-t2").textContent = fmt(sig.target2);
      $("sc-size").textContent = sig.contracts + "x MNQ";
      $("sc-risk").textContent = fmtMoney(sig.risk_dollars);
      const ul = $("sc-reasons");
      ul.innerHTML = "";
      (sig.reasons || []).forEach((r) => {
        const li = document.createElement("li");
        li.textContent = r;
        ul.appendChild(li);
      });
      startTtl(sig);
    } else {
      card.className = "stand-aside";
      $("sc-status").textContent = "STAND ASIDE";
      $("sc-reason").textContent = standAsideReason || "no qualified setup";
      body.classList.add("hidden");
      stopTtl();
    }
    drawSignalLines(sig && (sig.status === "OPEN" || sig.status === "ACTIVE") ? sig : null);
  }

  function startTtl(sig) {
    stopTtl();
    const el = $("sc-ttl");
    ttlTimer = setInterval(() => {
      const left = Math.round(sig.expires_at - Date.now() / 1000);
      el.textContent = left > 0
        ? "act within " + left + "s — don't chase after that"
        : "entry window closed — tracking outcome, do not chase";
    }, 500);
  }
  function stopTtl() { if (ttlTimer) clearInterval(ttlTimer); ttlTimer = null; }

  function renderStats(today, all) {
    if (today) {
      const pnl = $("stat-pnl");
      pnl.textContent = fmtMoney(today.pnl_dollars);
      pnl.className = today.pnl_dollars > 0 ? "pnl-pos" : today.pnl_dollars < 0 ? "pnl-neg" : "";
      $("stat-wr").textContent = today.resolved ? today.win_rate + "%" : "—";
      $("stat-count").textContent = today.signals;
    }
    if (all) {
      $("alltime-line").textContent =
        " all-time: " + all.resolved + " resolved, " + all.win_rate + "% win, " +
        fmtMoney(all.pnl_dollars) + ", avg " + all.avg_r + "R";
    }
  }

  function renderHistory(signals) {
    const tbody = document.querySelector("#history tbody");
    tbody.innerHTML = "";
    signals.forEach((s) => upsertHistoryRow(s, tbody, true));
  }

  function upsertHistoryRow(s, tbody, append) {
    tbody = tbody || document.querySelector("#history tbody");
    let row = document.getElementById("sig-" + s.id);
    if (!row) {
      row = document.createElement("tr");
      row.id = "sig-" + s.id;
      if (append) tbody.appendChild(row);
      else tbody.insertBefore(row, tbody.firstChild);
    }
    const t = new Date(s.ts * 1000);
    const hh = t.getHours().toString().padStart(2, "0");
    const mm = t.getMinutes().toString().padStart(2, "0");
    const pnl = s.pnl_dollars;
    row.innerHTML =
      "<td>" + hh + ":" + mm + "</td>" +
      '<td><span class="badge ' + s.direction + '">' + s.direction + " " + s.grade + "</span></td>" +
      "<td>" + fmt(s.entry) + "</td>" +
      '<td><span class="badge ' + s.status + '">' + s.status.replace("_", " ") + "</span></td>" +
      '<td class="' + (pnl > 0 ? "pnl-pos" : pnl < 0 ? "pnl-neg" : "") + '">' +
      (pnl == null ? "—" : fmtMoney(pnl)) + "</td>";
  }

  function renderVotes(votes) {
    const ul = $("votes");
    ul.innerHTML = "";
    if (!votes || !votes.length) {
      ul.innerHTML = '<li class="muted">no active votes — neutral tape</li>';
      return;
    }
    votes.sort((a, b) => b.weight - a.weight).forEach((v) => {
      const li = document.createElement("li");
      li.className = v.direction.toLowerCase();
      li.innerHTML = '<span class="w">' + (v.direction === "LONG" ? "+" : "−") +
        v.weight.toFixed(1) + "</span><span>" + v.reason + "</span>";
      ul.appendChild(li);
    });
  }

  function renderStructure(st) {
    if (!st) return;
    const htf = st.htf_bias || "unknown";
    $("struct-htf").textContent = "HTF bias: " + htf;
    for (const tf of ["1h", "15m", "5m", "1m"]) {
      const el = $("st-" + tf);
      const row = st[tf];
      if (!el || !row) continue;
      let txt = row.bias;
      if (row.last_event) {
        const ev = row.last_event;
        txt += " · " + ev.kind + " " + ev.direction + " @ " + ev.level;
        if (ev.bars_ago === 0) txt += " (now)";
        else if (ev.bars_ago <= 3) txt += " (" + ev.bars_ago + " bars ago)";
      }
      el.textContent = txt;
      el.className = row.bias === "bullish" ? "struct-bull"
        : row.bias === "bearish" ? "struct-bear" : "struct-range";
    }
  }

  function applyState(st) {
    if (!st || !st.price) return;
    const priceEl = $("price");
    priceEl.textContent = fmt(st.price);
    priceEl.className = "big-price " +
      (lastPrice != null ? (st.price > lastPrice ? "up" : st.price < lastPrice ? "down" : "") : "");
    lastPrice = st.price;
    $("bidask").textContent = "bid " + fmt(st.bid) + " / ask " + fmt(st.ask);
    $("phase").textContent = (st.phase || "—").replace("_", " ");
    $("clock").textContent = new Date(st.ts * 1000).toLocaleTimeString("en-US",
      { timeZone: "America/New_York", hour12: false }) + " ET";

    $("ro-vwap").textContent = fmt(st.vwap);
    $("ro-ema1").textContent = fmt(st.ema9_1m) + " / " + fmt(st.ema21_1m);
    $("ro-ema5").textContent = fmt(st.ema9_5m) + " / " + fmt(st.ema21_5m);
    $("ro-rsi").textContent = fmt(st.rsi_1m, 0);
    $("ro-atr").textContent = fmt(st.atr_5m, 1) + " pts";
    $("ro-rvol").textContent = st.rvol_1m == null ? "—" : fmt(st.rvol_1m, 1) + "x";

    setLine("VWAP", st.vwap, "#d29922", LightweightCharts.LineStyle.Solid, "VWAP");
    if (st.vwap != null && st.vwap_sigma != null) {
      setLine("VWAP+2", st.vwap + 2 * st.vwap_sigma, "rgba(210,153,34,0.5)",
        LightweightCharts.LineStyle.Dotted, "+2σ");
      setLine("VWAP-2", st.vwap - 2 * st.vwap_sigma, "rgba(210,153,34,0.5)",
        LightweightCharts.LineStyle.Dotted, "-2σ");
    }
    // Time-of-day noise band: beyond it = statistically abnormal displacement
    // (trend-day evidence); inside it = normal wander, breakouts carry no edge.
    setLine("NOISE+", st.noise_upper, "rgba(63,185,80,0.55)",
      LightweightCharts.LineStyle.SparseDotted, "noise+");
    setLine("NOISE-", st.noise_lower, "rgba(248,81,73,0.55)",
      LightweightCharts.LineStyle.SparseDotted, "noise-");
    if (st.levels) {
      const L = st.levels;
      setLine("PDH", L.prior_day_high, "#8b949e", LightweightCharts.LineStyle.Dashed, "PDH");
      setLine("PDL", L.prior_day_low, "#8b949e", LightweightCharts.LineStyle.Dashed, "PDL");
      setLine("ONH", L.overnight_high, "#388bfd", LightweightCharts.LineStyle.Dashed, "ONH");
      setLine("ONL", L.overnight_low, "#388bfd", LightweightCharts.LineStyle.Dashed, "ONL");
      setLine("ORH", L.opening_range_done ? L.opening_range_high : null,
        "#bc8cff", LightweightCharts.LineStyle.Dashed, "ORH");
      setLine("ORL", L.opening_range_done ? L.opening_range_low : null,
        "#bc8cff", LightweightCharts.LineStyle.Dashed, "ORL");
    }

    renderVotes(st.votes);
    renderStructure(st.structure);
    $("chop-line").textContent = st.chop ? "⚠ " + st.chop_detail : (st.chop_detail || "");

    const banner = $("breaker-banner");
    if (st.breaker_tripped) {
      banner.classList.remove("hidden");
      $("breaker-text").textContent = st.breaker_losses +
        " stop-outs today. Engine locked until tomorrow. Protect the account.";
    } else {
      banner.classList.add("hidden");
    }

    // Advisory-only: the engine saw an abnormal bar and is standing aside on
    // purpose (chasing these measured net-negative over 25 real sessions).
    const dispBanner = $("displacement-banner");
    if (st.displacement) {
      const d = st.displacement;
      const ageMin = Math.floor(Math.max(0, st.ts - d.ts - 60) / 60);
      dispBanner.classList.remove("hidden");
      $("displacement-text").textContent =
        fmt(d.points, 0) + "-pt 1m bar (" + d.atr_mult + "x ATR) on " +
        fmt(d.rvol, 1) + "x volume, heavy " +
        (d.direction === "SELL" ? "selling" : "buying") +
        (ageMin >= 1 ? ", " + ageMin + "m ago" : "") +
        ". Momentum regime — don't fade it; wait for a confirmed setup.";
    } else {
      dispBanner.classList.add("hidden");
    }

    // Advisory-only: the one pattern that persisted across the 2019-2026
    // research corpus (PF 2.17, t 2.9) but is UNVALIDATED at ~10 events/yr.
    // Context for the discretionary trader; the engine never trades it.
    const lvlBanner = $("levels-break-banner");
    if (st.levels_break) {
      const lb = st.levels_break;
      const ageMin = Math.floor(Math.max(0, st.ts - lb.ts) / 60);
      lvlBanner.classList.remove("hidden");
      $("levels-break-text").textContent =
        lb.level + " " + fmt(lb.px, 2) + " broken " +
        (lb.direction === "BUY" ? "upward" : "downward") + " by " +
        fmt(lb.through_pts, 1) + " pts after an approach from distance" +
        (ageMin >= 1 ? ", " + ageMin + "m ago" : "") +
        ". Rare 7-year-persistent pattern; unvalidated — context, not a call.";
    } else {
      lvlBanner.classList.add("hidden");
    }

    activeSignal = st.open_signal || activeSignal;
    if (st.open_signal) setSignalCard(st.open_signal, null);
    else if (!activeSignal || ["TARGET1", "TARGET2", "STOPPED", "FLAT_EXIT", "EXPIRED_UNFILLED"]
      .includes(activeSignal.status)) {
      setSignalCard(null, st.standing_aside);
    }
  }

  // ---------- stop server ----------
  let intentionalShutdown = false;

  function showStoppedOverlay() {
    $("stopped-overlay").classList.remove("hidden");
    document.title = "Trade Copilot — stopped";
  }

  async function stopCopilot() {
    if (!confirm("Stop Trade Copilot?\n\nThe engine will shut down and this dashboard will go offline.")) {
      return;
    }
    intentionalShutdown = true;
    $("stop-btn").disabled = true;
    $("feed-label").textContent = "stopping…";
    try {
      await fetch("/api/shutdown", { method: "POST" });
    } catch (e) { /* server may exit before the response finishes */ }
    showStoppedOverlay();
  }

  $("stop-btn").onclick = stopCopilot;

  // ---------- settings modal ----------
  const modal = $("settings-modal");
  modal.classList.add("hidden");
  $("settings-btn").onclick = () => {
    const form = $("settings-form");
    for (const el of form.elements) {
      if (!el.name) continue;
      if (el.type === "checkbox") el.checked = !!settings[el.name];
      else if (settings[el.name] != null) el.value = settings[el.name];
    }
    modal.classList.remove("hidden");
  };
  $("settings-cancel").onclick = () => modal.classList.add("hidden");
  $("settings-form").onsubmit = async (e) => {
    e.preventDefault();
    const patch = {};
    for (const el of e.target.elements) {
      if (!el.name) continue;
      patch[el.name] = el.type === "checkbox" ? el.checked : Number(el.value);
    }
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    settings = await res.json();
    modal.classList.add("hidden");
  };

  // ---------- websocket ----------
  function connect() {
    const ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") +
      location.host + "/ws");
    const dot = document.querySelector("#feed-dot .dot");

    ws.onopen = () => { dot.className = "dot live"; $("feed-label").textContent = "live"; };
    ws.onclose = () => {
      if (intentionalShutdown) {
        dot.className = "dot stale";
        $("feed-label").textContent = "stopped";
        return;
      }
      dot.className = "dot stale";
      $("feed-label").textContent = "reconnecting…";
      setTimeout(connect, 2000);
    };
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.type === "init") {
        settings = msg.settings || {};
        $("symbol").textContent = msg.symbol + "  ·  " + msg.feed_mode + " feed";
        if (msg.bars_1m && msg.bars_1m.length) setChartData(msg.bars_1m);
        renderHistory(msg.signals || []);
        renderStats(msg.stats_today, msg.stats_all);
        if (msg.state && msg.state.price) applyState(msg.state);
      } else if (msg.type === "bar") {
        updateChartBar(msg.bar);
      } else if (msg.type === "state") {
        applyState(msg);
      } else if (msg.type === "signal") {
        activeSignal = msg.signal;
        setSignalCard(msg.signal, null);
        upsertHistoryRow(msg.signal);
        renderStats(msg.stats_today, null);
        $("signal-card").classList.add("flash");
        setTimeout(() => $("signal-card").classList.remove("flash"), 2200);
        chime("signal");
        document.title = "⚡ " + msg.signal.direction + " MNQ — Trade Copilot";
        setTimeout(() => { document.title = "Trade Copilot — MNQ"; }, 30000);
      } else if (msg.type === "signal_update") {
        upsertHistoryRow(msg.signal);
        renderStats(msg.stats_today, msg.stats_all);
        if (activeSignal && activeSignal.id === msg.signal.id) {
          activeSignal = msg.signal;
          if (["TARGET1", "TARGET2"].includes(msg.signal.status)) chime("win");
          else if (msg.signal.status === "STOPPED") chime("loss");
          if (msg.signal.status !== "OPEN") setSignalCard(null, "signal resolved: " +
            msg.signal.status.replace("_", " ") + " (" + fmtMoney(msg.signal.pnl_dollars) + ")");
        }
      } else if (msg.type === "settings") {
        settings = msg.settings;
      } else if (msg.type === "shutdown") {
        intentionalShutdown = true;
        $("stop-btn").disabled = true;
        $("feed-label").textContent = "stopped";
        showStoppedOverlay();
      }
    };
  }
  connect();
})();
