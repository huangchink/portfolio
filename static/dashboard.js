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
      roe: "roe",
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
      (item) => number(item.forward_pe) !== null && number(item.roe) !== null
    );
    if (empty) empty.hidden = valid.length > 0;

    valid.forEach((item) => {
      const forwardPe = Math.max(0, Math.min(number(item.forward_pe), 60));
      const roe = Math.max(-20, Math.min(number(item.roe), 80));
      const weight = Math.max(0, number(item.portfolio_weight) || 0);
      const dot = document.createElement("button");
      dot.type = "button";
      dot.className = "map-dot";
      dot.style.left = `${(forwardPe / 60) * 96 + 2}%`;
      dot.style.bottom = `${((roe + 20) / 100) * 92 + 4}%`;
      dot.style.setProperty("--dot-size", `${Math.min(58, 28 + Math.sqrt(weight) * 5)}px`);
      dot.textContent = item.symbol;
      dot.title = `${item.symbol} · Forward P/E ${multiple(item.forward_pe)} · ROE ${percent(item.roe)}`;
      dot.setAttribute("aria-label", dot.title);
      dot.addEventListener("click", () => openDialog(item.symbol));
      map.appendChild(dot);
    });
  }

  const dialog = document.querySelector("#stockDialog");
  const dialogClose = document.querySelector("#dialogClose");

  function makeCommentary(item) {
    const notes = [];
    const roe = number(item.roe);
    const trailing = number(item.trailing_pe);
    const forward = number(item.forward_pe);
    const ath = number(item.ath_distance);

    if (roe === null) notes.push("目前缺少可比的 ROE 資料");
    else if (roe >= 25) notes.push("ROE 顯示資本使用效率強，但仍需確認是否受低權益基數或庫藏股影響");
    else if (roe >= 15) notes.push("ROE 位於穩健區間");
    else if (roe >= 0) notes.push("ROE 偏低，建議搭配營業利益率與資產週轉率判讀");
    else notes.push("ROE 為負，獲利品質仍需改善");

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
      ["ROE · TTM", percent(item.roe)],
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

  function escapeCsv(value) {
    const text = String(value ?? "");
    return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
  }

  document.querySelector("#exportButton")?.addEventListener("click", () => {
    const headers = [
      "Symbol", "Company", "Sector", "Shares", "Average Cost", "Price", "Market Value",
      "Weight %", "Trailing PE", "Forward PE", "ROE %", "ROI %", "Buyback TTM",
      "Buyback Active", "All-time High", "Distance from ATH %",
    ];
    const records = items.map((item) => [
      item.symbol, item.name, item.sector, item.shares, item.cost, item.price, item.market_value,
      item.portfolio_weight, item.trailing_pe, item.forward_pe, item.roe, item.roi,
      item.buyback_ttm, item.is_buying_back, item.ath, item.ath_distance,
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
})();
