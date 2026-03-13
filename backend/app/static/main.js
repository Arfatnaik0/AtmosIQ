"use strict";

// ── Chart instances ──
let charts = {};

// ── Chart.js global defaults ──
Chart.defaults.color          = "#55524c";
Chart.defaults.borderColor    = "rgba(255,255,255,0.045)";
Chart.defaults.font.family    = "'IBM Plex Mono', monospace";
Chart.defaults.font.size      = 11;
Chart.defaults.plugins.legend.display = false;

const CHART_OPTS = {
  responsive: true,
  maintainAspectRatio: false,
  interaction: { mode: "nearest", intersect: false },
  plugins: {
    tooltip: {
      backgroundColor: "#141512",
      borderColor: "rgba(78,122,95,0.28)",
      borderWidth: 1,
      titleColor: "#e8e4da",
      bodyColor: "#7a776f",
      padding: 12,
      cornerRadius: 8,
    }
  },
  scales: {
    x: {
      grid: { color: "rgba(255,255,255,0.03)" },
      ticks: { maxTicksLimit: 8 }
    },
    y: {
      grid: { color: "rgba(255,255,255,0.03)" },
      ticks: { maxTicksLimit: 5 }
    }
  }
};

// ── AQI colour scale (India AQI) ──
function aqiColor(aqi) {
  if (aqi <= 50)  return "#4e7a5f";
  if (aqi <= 100) return "#84a84d";
  if (aqi <= 200) return "#c8922a";
  if (aqi <= 300) return "#c85f30";
  if (aqi <= 400) return "#c43838";
  return "#7b68b8";
}

function aqiCategory(aqi) {
  if (aqi <= 50)  return "Good";
  if (aqi <= 100) return "Satisfactory";
  if (aqi <= 200) return "Moderate";
  if (aqi <= 300) return "Poor";
  if (aqi <= 400) return "Very Poor";
  return "Severe";
}

// ── Helpers ──
function el(id) { return document.getElementById(id); }

function destroyChart(key) {
  if (charts[key]) { charts[key].destroy(); delete charts[key]; }
}

function makeTimeLabel(ts) {
  return ts.slice(11, 16);
}

// ── Live clock (IST) ──
function updateClock() {
  const now = new Date();
  const h = String(now.getHours()).padStart(2, "0");
  const m = String(now.getMinutes()).padStart(2, "0");
  const clockEl = el("navClock");
  if (clockEl) clockEl.textContent = `${h}:${m}`;
}
updateClock();
setInterval(updateClock, 1000);

// ── Parallel fetch of all endpoints ──
async function fetchAll() {
  const endpoints = [
    "/api/history",
    "/api/weather",
    "/api/model-scorecard",
    "/api/trend",
    "/api/health-advisory",
    "/api/data-freshness",
    "/api/daily-summary",
    "/api/worst-hours",
  ];

  const results = await Promise.allSettled(
    endpoints.map(url => fetch(url).then(r => r.json()))
  );

  return {
    history:   results[0].status === "fulfilled" ? results[0].value : null,
    weather:   results[1].status === "fulfilled" ? results[1].value : null,
    scorecard: results[2].status === "fulfilled" ? results[2].value : null,
    trend:     results[3].status === "fulfilled" ? results[3].value : null,
    advisory:  results[4].status === "fulfilled" ? results[4].value : null,
    freshness: results[5].status === "fulfilled" ? results[5].value : null,
    daily:     results[6].status === "fulfilled" ? results[6].value : null,
    worst:     results[7].status === "fulfilled" ? results[7].value : null,
  };
}


// ── Render functions ──

function renderAqiCard(history) {
  if (!history || history.length < 4) return;

  const latest    = history[history.length - 1];
  const predicted = history[history.length - 4];

  const aqi   = latest.current_aqi;
  const pred  = predicted?.predicted_aqi_3h ?? null;
  const delta = pred !== null ? aqi - pred : null;
  const color = aqiColor(aqi);

  el("currentAQI").textContent = aqi;
  el("currentAQI").style.color = color;

  const badge = el("aqiCategory");
  badge.textContent = aqiCategory(aqi);
  badge.style.background = `${color}22`;
  badge.style.color = color;

  el("predictedNow").textContent = pred !== null ? pred : "--";

  if (delta !== null) {
    el("aqiDelta").textContent = delta > 0 ? `+${delta}` : `${delta}`;
    el("aqiDelta").style.color = Math.abs(delta) <= 15 ? "#4e7a5f" : "#c43838";
  }
}

function renderTrend(data) {
  if (!data || data.trend === "unknown") return;

  const icons  = { up: "↑", down: "↓", stable: "→" };
  const colors = { up: "#c43838", down: "#4e7a5f", stable: "#c8922a" };

  el("trendIcon").textContent  = icons[data.trend] || "—";
  el("trendIcon").style.color  = colors[data.trend] || "#55524c";
  el("trendLabel").textContent = data.trend;
  el("trendSlope").textContent = `slope: ${data.slope > 0 ? "+" : ""}${data.slope}`;
}

function renderWeather(data) {
  if (!data) return;
  el("tempVal").textContent     = data.temperature !== null ? Math.round(data.temperature) : "--";
  el("humidityVal").textContent = `Humidity: ${data.humidity ?? "--"}%`;
  el("windSpeed").textContent   = data.ws_ms !== null ? data.ws_ms : "--";
  el("windDir").textContent     = `Direction: ${data.wd_deg ?? "--"}°`;
}

function renderScorecard(data) {
  if (!data || data.error) return;
  el("maeVal").textContent     = data.mae;
  el("maeSamples").textContent = `samples: ${data.sample_size}`;
}

function renderFreshness(data) {
  if (!data || data.error) return;

  // Stored timestamp is naive IST — subtract 5h30m offset to get UTC
  const IST_OFFSET_MS = 5.5 * 60 * 60 * 1000;
  const storedMs    = new Date(data.latest_timestamp.replace(" ", "T")).getTime();
  const storedUtcMs = storedMs - IST_OFFSET_MS;
  const mins        = Math.round((Date.now() - storedUtcMs) / 60000);

  const isStale = mins > 90;
  el("freshnessVal").textContent    = mins;
  el("freshnessStatus").textContent = isStale ? "⚠ stale" : "✓ live";
  el("freshnessCard").classList.toggle("stale", isStale);
}

function renderAdvisory(data) {
  if (!data || data.error) return;
  const banner = el("advisoryBanner");
  banner.classList.remove("hidden");
  banner.style.background   = `${data.color}12`;
  banner.style.borderColor  = `${data.color}38`;

  const cat = el("advisoryCategory");
  cat.textContent       = data.category;
  cat.style.background  = `${data.color}28`;
  cat.style.color       = data.color;

  el("advisoryMessage").textContent = data.message;
}


// ── Chart renders ──

function renderAqiChart(history) {
  if (!history || history.length < 4) return;
  destroyChart("aqi");

  const labels   = history.map(d => makeTimeLabel(d.timestamp_utc));
  const actual   = history.map(d => d.current_aqi);
  const forecast = [
    ...Array(history.length - 1).fill(null),
    actual[actual.length - 1],
    ...history.slice(-3).map(d => d.predicted_aqi_3h)
  ];
  const extLabels = [...labels, "+1h", "+2h", "+3h"];

  const ctx = el("aqiChart").getContext("2d");
  charts.aqi = new Chart(ctx, {
    type: "line",
    data: {
      labels: extLabels,
      datasets: [
        {
          label: "Actual AQI",
          data: [...actual, null, null, null],
          borderColor: "#c43838",
          backgroundColor: "rgba(196,56,56,0.06)",
          fill: true,
          tension: 0.4,
          pointRadius: 0,
          pointHoverRadius: 5,
          borderWidth: 1.5,
        },
        {
          label: "Forecast",
          data: forecast,
          borderColor: "#6aab82",
          borderDash: [6, 4],
          backgroundColor: "rgba(106,171,130,0.04)",
          fill: true,
          tension: 0.4,
          pointRadius: 0,
          pointHoverRadius: 5,
          borderWidth: 1.5,
        }
      ]
    },
    options: {
      ...CHART_OPTS,
      plugins: { ...CHART_OPTS.plugins, legend: { display: false } }
    }
  });
}

// PM2.5 — thin bar chart (like reference design)
function renderPm25Chart(history) {
  if (!history) return;
  destroyChart("pm25");

  const ctx = el("pm25Chart").getContext("2d");
  charts.pm25 = new Chart(ctx, {
    type: "bar",
    data: {
      labels: history.map(d => makeTimeLabel(d.timestamp_utc)),
      datasets: [{
        label: "PM2.5",
        data: history.map(d => d.pm2_5),
        backgroundColor: "rgba(0,200,224,0.5)",
        hoverBackgroundColor: "rgba(0,200,224,0.75)",
        borderRadius: 2,
        barPercentage: 0.45,
        categoryPercentage: 0.65,
      }]
    },
    options: CHART_OPTS
  });
}

// PM10 — thin bar chart (like reference design)
function renderPm10Chart(history) {
  if (!history) return;
  destroyChart("pm10");

  const ctx = el("pm10Chart").getContext("2d");
  charts.pm10 = new Chart(ctx, {
    type: "bar",
    data: {
      labels: history.map(d => makeTimeLabel(d.timestamp_utc)),
      datasets: [{
        label: "PM10",
        data: history.map(d => d.pm10),
        backgroundColor: "rgba(123,104,184,0.5)",
        hoverBackgroundColor: "rgba(123,104,184,0.75)",
        borderRadius: 2,
        barPercentage: 0.45,
        categoryPercentage: 0.65,
      }]
    },
    options: CHART_OPTS
  });
}

function renderDailyChart(daily) {
  if (!daily || daily.length === 0) return;
  destroyChart("daily");

  const labels = daily.map(d => d.date.slice(5));
  const avgAqi = daily.map(d => d.avg_aqi);
  const minAqi = daily.map(d => d.min_aqi);
  const maxAqi = daily.map(d => d.max_aqi);

  const ctx = el("dailyChart").getContext("2d");
  charts.daily = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "Max",
          data: maxAqi,
          backgroundColor: "rgba(196,56,56,0.5)",
          borderRadius: 3,
          order: 1,
        },
        {
          label: "Avg",
          data: avgAqi,
          backgroundColor: "rgba(0,200,224,0.4)",
          borderRadius: 3,
          order: 2,
        },
        {
          label: "Min",
          data: minAqi,
          backgroundColor: "rgba(78,122,95,0.55)",
          borderRadius: 3,
          order: 3,
        }
      ]
    },
    options: {
      ...CHART_OPTS,
      plugins: {
        ...CHART_OPTS.plugins,
        legend: {
          display: true,
          position: "top",
          labels: {
            boxWidth: 8,
            padding: 16,
            color: "#55524c",
            font: { size: 10 }
          }
        }
      }
    }
  });
}

function renderWorstHoursChart(worst) {
  if (!worst || worst.length === 0) return;
  destroyChart("worst");

  const ctx = el("worstHoursChart").getContext("2d");
  charts.worst = new Chart(ctx, {
    type: "bar",
    data: {
      labels: worst.map(d => `${String(d.hour).padStart(2, "0")}:00`),
      datasets: [{
        label: "Avg AQI",
        data: worst.map(d => d.avg_aqi),
        backgroundColor: worst.map(d => `${aqiColor(d.avg_aqi)}99`),
        hoverBackgroundColor: worst.map(d => `${aqiColor(d.avg_aqi)}dd`),
        borderRadius: 3,
        barPercentage: 0.7,
        categoryPercentage: 0.8,
      }]
    },
    options: CHART_OPTS
  });
}


// ── Boot ──
async function renderDashboard(isFirstLoad = false) {
  const data = await fetchAll();

  renderAqiCard(data.history);
  renderTrend(data.trend);
  renderWeather(data.weather);
  renderScorecard(data.scorecard);
  renderFreshness(data.freshness);
  renderAdvisory(data.advisory);

  renderAqiChart(data.history);
  renderPm25Chart(data.history);
  renderPm10Chart(data.history);
  renderDailyChart(data.daily);
  renderWorstHoursChart(data.worst);

  if (isFirstLoad) {
    setTimeout(() => {
      el("loadingOverlay").classList.add("hidden");
    }, 90);
  }
}

// Initial render
renderDashboard(true);

// Auto-refresh every 15 minutes
setInterval(() => renderDashboard(false), 15 * 60 * 1000);