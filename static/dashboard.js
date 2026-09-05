(() => {
  "use strict";

  const dashboard = window.__PORTFOLIO_DATA__ || { items: [], summary: {} };
  const items = dashboard.items || [];
  const itemMap = new Map(items.map((item) => [item.symbol, item]));
  const body = document.querySelector("#holdingsBody");
  const rows = body ? Array.from(body.querySelectorAll("tr")) : [];
  const searchInput = document.querySelector("#searchInput");
  const sectorFilter = document.querySelector("#sectorFilter");
  const sortSelect = document.querySelector("#sortSelect");
  const buybackFilter = document.querySelector("#buybackFilter");
  const athFilter = document.querySelector("#athFilter");
  const resultCount = document.querySelector("#resultCount");
  const emptyState = document.querySelector("#emptyState");
  const clearFilters = document.querySelector("#clearFilters");
  let buybackOnly = false;
  let nearAthOnly = false;

  const number = (value) => {
    if (value === null || value === undefined || value === "") return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  };

  const money = (value, digits = 2) => {
    const parsed = number(value);
    return parsed === null
      ? "—"
      : `$${parsed.toLocaleString("en-US", {
          minimumFractionDigits: digits,
          maximumFractionDigits: digits,
        })}`;
  };

  const compactMoney = (value) => {
    const parsed = number(value);
    if (parsed === null) return "—";
    return new Intl.NumberFormat("zh-TW", {
      style: "currency",
      currency: "USD",
      notation: "compact",
      maximumFractionDigits: 1,
    }).format(parsed);
  };

  const percent = (value, signed = false) => {
    const parsed = number(value);
    if (parsed === null) return "—";
    const sign = signed && parsed > 0 ? "+" : "";
    return `${sign}${parsed.toFixed(1)}%`;
  };

  const multiple = (value) => {
    const parsed = number(value);
    return parsed === null ? "—" : `${parsed.toFixed(1)}×`;
  };

  function applyFiltersAndSort() {
    if (!body) return;
    const query = (searchInput?.value || "").trim().toLowerCase();
    const sector = sectorFilter?.value || "all";
    let visible = 0;

    rows.forEach((row) => {
      const matchesText =
        !query ||
        row.dataset.symbol.toLowerCase().includes(query) ||
        row.dataset.name.toLowerCase().includes(query);
      const matchesSector = sector === "all" || row.dataset.sector === sector;
      const matchesBuyback = !buybackOnly || row.dataset.buyback === "true";
      const ath = number(row.dataset.ath);
      const matchesAth = !nearAthOnly || (ath !== null && ath >= -10);
      const show = matchesText && matchesSector && matchesBuyback && matchesAth;
      row.hidden = !show;
      if (show) visible += 1;
    });

    const sort = sortSelect?.value || "weight-desc";
    const [field, direction] = sort.split("-");
    const fieldMap = {
      weight: "weight",
      forwardPe: "forwardPe",
      roa: "roa",
      roi: "roi",
      ath: "ath",
    };
    const datasetKey = fieldMap[field] || "weight";
    const sorted = [...rows].sort((left, right) => {
      const a = number(left.dataset[datasetKey]);
      const b = number(right.dataset[datasetKey]);
      if (a === null && b === null) return left.dataset.symbol.localeCompare(right.dataset.symbol);
      if (a === null) return 1;
      if (b === null) return -1;
      return direction === "asc" ? a - b : b - a;
    });
    sorted.forEach((row) => body.appendChild(row));

    if (resultCount) resultCount.textContent = String(visible).padStart(2, "0");
    if (emptyState) emptyState.hidden = visible !== 0;
  }

  searchInput?.addEventListener("input", applyFiltersAndSort);
  sectorFilter?.addEventListener("change", applyFiltersAndSort);
  sortSelect?.addEventListener("change", applyFiltersAndSort);

  buybackFilter?.addEventListener("click", () => {
    buybackOnly = !buybackOnly;
    buybackFilter.setAttribute("aria-pressed", String(buybackOnly));
    applyFiltersAndSort();
  });

  athFilter?.addEventListener("click", () => {
    nearAthOnly = !nearAthOnly;
    athFilter.setAttribute("aria-pressed", String(nearAthOnly));
    applyFiltersAndSort();
  });

  clearFilters?.addEventListener("click", () => {
    if (searchInput) searchInput.value = "";
    if (sectorFilter) sectorFilter.value = "all";
    buybackOnly = false;
    nearAthOnly = false;
    buybackFilter?.setAttribute("aria-pressed", "false");
    athFilter?.setAttribute("aria-pressed", "false");
    applyFiltersAndSort();
  });

  document.addEventListener("keydown", (event) => {
    if (
      event.key === "/" &&
      document.activeElement?.tagName !== "INPUT" &&
      document.activeElement?.tagName !== "SELECT"
    ) {
      event.preventDefault();
      searchInput?.focus();
    }
  });

  function buildValuationMap() {
    const map = document.querySelector("#valuationMap");
    const empty = document.querySelector("#mapEmpty");
    if (!map) return;
    const valid = items.filter(
      (item) => number(item.forward_pe) !== null && number(item.roa) !== null
    );
    if (empty) empty.hidden = valid.length > 0;

    valid.forEach((item) => {
      const forwardPe = Math.max(0, Math.min(number(item.forward_pe), 60));
      const roa = Math.max(-10, Math.min(number(item.roa), 30));
      const weight = Math.max(0, number(item.portfolio_weight) || 0);
      const dot = document.createElement("button");
      dot.type = "button";
      dot.className = "map-dot";
      dot.style.left = `${(forwardPe / 60) * 96 + 2}%`;
      dot.style.bottom = `${((roa + 10) / 40) * 92 + 4}%`;
      dot.style.setProperty("--dot-size", `${Math.min(58, 28 + Math.sqrt(weight) * 5)}px`);
      dot.textContent = item.symbol;
      dot.title = `${item.symbol} · Forward P/E ${multiple(item.forward_pe)} · ROA ${percent(item.roa)}`;
      dot.setAttribute("aria-label", dot.title);
      dot.addEventListener("click", () => openDialog(item.symbol));
      map.appendChild(dot);
    });
  }

  function buildTopHoldingsChart() {
    const donut = document.querySelector("#holdingsDonut");
    const canvas = document.querySelector("#holdingsDonutCanvas");
    const list = document.querySelector("#topHoldingsList");
    const concentrationLabel = document.querySelector("#topTenConcentration");
    if (!donut || !canvas || !list) return;

    const ranked = items
      .filter((item) => number(item.market_value) !== null)
      .sort((left, right) => number(right.market_value) - number(left.market_value));
    const topTen = ranked.slice(0, 10);
    const total = ranked.reduce((sum, item) => sum + number(item.market_value), 0);
    if (!total || !topTen.length) {
      if (concentrationLabel) concentrationLabel.textContent = "—";
      list.innerHTML = "<li><span>目前沒有足夠的持倉市值資料</span></li>";
      return;
    }

    const colors = [
      "#4e9af1", "#f16b4e", "#4ecf8a", "#b06cf7", "#f7c24e",
      "#4ec8f7", "#f74e8e", "#7ecf4e", "#f74e4e", "#4e6ff7",
      "#f7934e",
    ];
    const concentration = topTen.reduce(
      (sum, item) => sum + (number(item.market_value) / total) * 100,
      0
    );
    const otherValue = ranked.slice(10).reduce(
      (sum, item) => sum + number(item.market_value),
      0
    );
    const chartItems = [
      ...topTen,
      ...(otherValue > 0
        ? [{ symbol: "Others", name: "其他持股", market_value: otherValue }]
        : []),
    ];
    donut.setAttribute(
      "aria-label",
      `前十大持股占投資組合 ${concentration.toFixed(1)}%，依序為 ${topTen.map((item) => item.symbol).join("、")}`
    );
    if (concentrationLabel) concentrationLabel.textContent = `${concentration.toFixed(1)}%`;

    list.innerHTML = chartItems
      .map((item, index) => {
        const weight = (number(item.market_value) / total) * 100;
        return `<li style="--slice-color: ${colors[index]}">
          <span class="holding-rank">${index < 10 ? String(index + 1).padStart(2, "0") : "—"}</span>
          <i class="holding-color" aria-hidden="true"></i>
          <span class="holding-name"><strong>${item.symbol}</strong><small>${index < 10 ? compactMoney(item.market_value) : `其餘 ${Math.max(0, ranked.length - 10)} 檔`}</small></span>
          <span class="holding-weight">${weight.toFixed(1)}%</span>
        </li>`;
      })
      .join("");

    if (!window.Chart) {
      let cursor = 0;
      const slices = chartItems.map((item, index) => {
        const weight = (number(item.market_value) / total) * 100;
        const slice = `${colors[index]} ${cursor.toFixed(3)}% ${(cursor + weight).toFixed(3)}%`;
        cursor += weight;
        return slice;
      });
      donut.style.background = `conic-gradient(${slices.join(", ")})`;
      donut.classList.add("is-fallback");
      canvas.hidden = true;
      return;
    }

    const logoImages = {};
    let chart = null;
    topTen.forEach((item, index) => {
      const image = new Image();
      image.src = `https://assets.parqet.com/logos/symbol/${encodeURIComponent(item.symbol)}?format=png`;
      image.addEventListener("load", () => chart?.draw());
      logoImages[index] = image;
    });

    const logoPlugin = {
      id: "portfolioLogoPlugin",
      afterDatasetDraw(chartInstance) {
        const context = chartInstance.ctx;
        const meta = chartInstance.getDatasetMeta(0);
        meta.data.forEach((element, index) => {
          const image = logoImages[index];
          if (!image?.complete || !image.naturalWidth) return;
          const { x, y } = element.tooltipPosition();
          const size = Math.max(24, Math.min(36, element.outerRadius - element.innerRadius - 8));
          context.save();
          context.beginPath();
          context.arc(x, y, size / 2 + 1, 0, Math.PI * 2);
          context.fillStyle = "rgba(255, 255, 255, 0.9)";
          context.fill();
          context.beginPath();
          context.arc(x, y, size / 2, 0, Math.PI * 2);
          context.clip();
          context.drawImage(image, x - size / 2, y - size / 2, size, size);
          context.restore();
        });
      },
    };

    chart = new window.Chart(canvas.getContext("2d"), {
      type: "doughnut",
      plugins: [logoPlugin],
      data: {
        labels: chartItems.map((item) => item.symbol),
        datasets: [{
          data: chartItems.map((item) => number(item.market_value)),
          backgroundColor: colors,
          borderColor: "#13221f",
          borderWidth: 3,
          hoverOffset: 10,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "62%",
        animation: { duration: 650 },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: "#07110f",
            borderColor: "rgba(240, 239, 232, 0.22)",
            borderWidth: 1,
            titleColor: "#f0efe8",
            bodyColor: "#c8ff36",
            padding: 12,
            callbacks: {
              label(context) {
                const value = context.parsed;
                const weight = (value / total) * 100;
                return ` ${money(value, 0)}  (${weight.toFixed(1)}%)`;
              },
            },
          },
        },
      },
    });
  }

  const dialog = document.querySelector("#stockDialog");
  const dialogClose = document.querySelector("#dialogClose");

  function makeCommentary(item) {
    const notes = [];
    const roa = number(item.roa);
    const trailing = number(item.trailing_pe);
    const forward = number(item.forward_pe);
    const ath = number(item.ath_distance);

    if (roa === null) notes.push("目前缺少可比的 ROA 資料");
    else if (roa >= 15) notes.push("ROA 顯示公司運用整體資產創造獲利的效率很強");
    else if (roa >= 8) notes.push("ROA 位於穩健區間，資產使用效率良好");
    else if (roa >= 0) notes.push("ROA 偏低，建議搭配營業利益率與資產週轉率判讀");
    else notes.push("ROA 為負，獲利品質仍需改善");

    if (forward !== null && trailing !== null) {
      if (forward < trailing * 0.9) notes.push("市場預期未來獲利成長，Forward P/E 明顯低於過去十二個月");
      else if (forward > trailing * 1.1) notes.push("Forward P/E 高於過去十二個月，市場預期獲利可能降溫");
      else notes.push("前瞻與過去估值接近，獲利預期相對平穩");
    } else if (forward !== null) {
      notes.push("目前僅有前瞻估值可供比較");
    } else {
      notes.push("本益比資料不足，可能與虧損或分析師覆蓋不足有關");
    }

    if (item.is_buying_back === true) notes.push("公司最近四個揭露季度有投入現金買回股票");
    else if (item.is_buying_back === false) notes.push("最近四季未見股票買回現金支出");
    else notes.push("回購現金流資料未完整揭露");

    if (ath !== null && ath >= -10) notes.push("股價位於歷史高檔區，估值紀律尤其重要");
    else if (ath !== null && ath <= -35) notes.push("距歷史高點較遠，需區分市場錯價與基本面永久性改變");
    return `${notes.join("；")}。`;
  }

  function openDialog(symbol) {
    const item = itemMap.get(symbol);
    if (!item || !dialog) return;

    dialog.querySelector("#dialogMonogram").textContent = item.symbol.slice(0, 2);
    dialog.querySelector("#dialogTitle").textContent = item.symbol;
    dialog.querySelector("#dialogName").textContent = `${item.name} · ${item.sector}`;
    dialog.querySelector("#dialogLabel").textContent = item.label;
    dialog.querySelector("#dialogPrice").textContent = money(item.price);
    const roi = dialog.querySelector("#dialogRoi");
    roi.textContent = `${percent(item.roi, true)} ROI`;
    roi.className = number(item.roi) !== null && number(item.roi) >= 0 ? "positive" : "negative";

    const metricData = [
      ["P/E · TTM", multiple(item.trailing_pe)],
      ["FORWARD P/E", multiple(item.forward_pe)],
      ["ROA · TTM", percent(item.roa)],
      ["距離 ATH", percent(item.ath_distance)],
    ];
    dialog.querySelector("#dialogMetrics").innerHTML = metricData
      .map(([label, value]) => `<div class="dialog-metric"><small>${label}</small><strong>${value}</strong></div>`)
      .join("");
    dialog.querySelector("#dialogCommentary").textContent = makeCommentary(item);
    dialog.querySelector("#dialogPosition").innerHTML = `
      <span><small>持有股數</small><strong>${Number(item.shares).toLocaleString("en-US", { maximumFractionDigits: 5 })}</strong></span>
      <span><small>平均成本</small><strong>${money(item.cost)}</strong></span>
      <span><small>部位市值</small><strong>${money(item.market_value, 0)}</strong></span>
    `;
    const link = dialog.querySelector("#dialogLink");
    link.href = item.quote_url;
    dialog.showModal();
  }

  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-open-symbol]");
    if (button) openDialog(button.dataset.openSymbol);
  });

  dialogClose?.addEventListener("click", () => dialog.close());
  dialog?.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });

  const buybackTooltip = document.querySelector("#buybackTooltip");
  let activeBuybackTrigger = null;

  function showBuybackTooltip(trigger) {
    if (!buybackTooltip || !trigger) return;
    activeBuybackTrigger = trigger;
    const state = trigger.dataset.buybackActive;
    const status = state === "true" ? "進行中" : state === "false" ? "未進行" : "未揭露";
    buybackTooltip.querySelector("#buybackTooltipTitle").textContent =
      `${trigger.dataset.buybackSymbol} · ${status}`;
    buybackTooltip.querySelector("#buybackTooltipAuthorized").textContent =
      state === "true" ? compactMoney(trigger.dataset.buybackAuthorized) : "—";
    buybackTooltip.querySelector("#buybackTooltipAmount").textContent =
      state === "true" ? compactMoney(trigger.dataset.buybackAmount) : "—";
    buybackTooltip.querySelector("#buybackTooltipPeriod").textContent =
      trigger.dataset.buybackPeriod || "未取得";
    buybackTooltip.querySelector("#buybackTooltipExpiry").textContent =
      trigger.dataset.buybackExpiry || "未取得";
    buybackTooltip.querySelector("#buybackTooltipSource").textContent =
      trigger.dataset.buybackForm !== "—"
        ? `${trigger.dataset.buybackForm} · ${trigger.dataset.buybackFiled}`
        : "未取得";
    buybackTooltip.dataset.state = state;
    buybackTooltip.hidden = false;

    const triggerRect = trigger.getBoundingClientRect();
    const tooltipRect = buybackTooltip.getBoundingClientRect();
    const gutter = 12;
    let left = triggerRect.left + triggerRect.width / 2 - tooltipRect.width / 2;
    left = Math.max(gutter, Math.min(left, window.innerWidth - tooltipRect.width - gutter));
    let top = triggerRect.top - tooltipRect.height - 10;
    if (top < gutter) top = triggerRect.bottom + 10;
    buybackTooltip.style.left = `${left}px`;
    buybackTooltip.style.top = `${top}px`;
  }

  function hideBuybackTooltip() {
    if (buybackTooltip) buybackTooltip.hidden = true;
    activeBuybackTrigger = null;
  }

  document.addEventListener("pointerover", (event) => {
    const trigger = event.target.closest(".buyback-trigger");
    if (trigger && trigger !== activeBuybackTrigger) showBuybackTooltip(trigger);
  });
  document.addEventListener("pointerout", (event) => {
    const trigger = event.target.closest(".buyback-trigger");
    if (trigger && !trigger.contains(event.relatedTarget)) hideBuybackTooltip();
  });
  document.addEventListener("focusin", (event) => {
    const trigger = event.target.closest(".buyback-trigger");
    if (trigger) showBuybackTooltip(trigger);
  });
  document.addEventListener("focusout", (event) => {
    const trigger = event.target.closest(".buyback-trigger");
    if (trigger && !trigger.contains(event.relatedTarget)) hideBuybackTooltip();
  });
  window.addEventListener("scroll", hideBuybackTooltip, { passive: true });
  window.addEventListener("resize", hideBuybackTooltip);

  function escapeCsv(value) {
    const text = String(value ?? "");
    return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
  }

  document.querySelector("#exportButton")?.addEventListener("click", () => {
    const headers = [
      "Symbol", "Company", "Sector", "Shares", "Average Cost", "Price", "Market Value",
      "Weight %", "Trailing PE", "Forward PE", "ROA %", "ROI %", "Buyback TTM",
      "Buyback Authorized", "Buyback Program Expiry", "Buyback Active", "SEC Filing",
      "SEC Source", "All-time High", "Distance from ATH %",
    ];
    const records = items.map((item) => [
      item.symbol, item.name, item.sector, item.shares, item.cost, item.price, item.market_value,
      item.portfolio_weight, item.trailing_pe, item.forward_pe, item.roa, item.roi,
      item.buyback_ttm, item.buyback_authorized_amount, item.buyback_program_expiry,
      item.is_buying_back,
      item.buyback_program_form && item.buyback_program_filed
        ? `${item.buyback_program_form} ${item.buyback_program_filed}`
        : "",
      item.buyback_program_source_url, item.ath, item.ath_distance,
    ]);
    const csv = [headers, ...records].map((row) => row.map(escapeCsv).join(",")).join("\n");
    const blob = new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `portfolio-fundamentals-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  });

  applyFiltersAndSort();
  buildValuationMap();
  buildTopHoldingsChart();
})();
