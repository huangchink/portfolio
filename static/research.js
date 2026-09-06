/* Pure calculations are also exported for the Node regression tests. */
(function () {
  'use strict';
  const num = value => value === null || value === undefined || value === '' || typeof value === 'boolean' ? null : Number.isFinite(Number(value)) ? Number(value) : null;
  const positive = value => num(value) !== null && num(value) > 0 ? num(value) : null;
  function scenario(eps, pe, price) {
    const e = positive(eps), p = positive(pe), current = positive(price);
    const target = e !== null && p !== null && Number.isFinite(e * p) ? e * p : null;
    return { target, change: target !== null && current !== null && Number.isFinite((target / current - 1) * 100) ? (target / current - 1) * 100 : null };
  }
  function initialAssumptions(item) {
    const eps = positive(item.scenario_eps), pe = positive(item.forward_pe);
    return Object.fromEntries([['bear', .8], ['base', 1], ['bull', 1.2]].map(([key, factor]) => [key, { eps: eps === null ? '' : String(Number((eps * factor).toPrecision(8))), pe: pe === null ? '' : String(Number((pe * factor).toPrecision(8))) }]));
  }
  function filteredItems(items, query, sector, attention, sort) {
    const q = query.trim().toLowerCase();
    return items.filter(i => `${i.symbol} ${i.name}`.toLowerCase().includes(q) && (sector === 'all' || i.sector === sector) && (!attention || i.research_notes.length > 0)).sort((a,b) => {
      if (sort === 'symbol') return a.symbol.localeCompare(b.symbol);
      if (sort === 'notes') return b.research_notes.length - a.research_notes.length || a.symbol.localeCompare(b.symbol);
      const av = num(a[sort]), bv = num(b[sort]);
      if (av === null && bv === null) return a.symbol.localeCompare(b.symbol);
      if (av === null) return 1;
      if (bv === null) return -1;
      return (sort === 'forward_pe' ? av - bv : bv - av) || a.symbol.localeCompare(b.symbol);
    });
  }
  const csvCell = value => '"' + String(value ?? '').replace(/^[=+@\-]/, "'$&").replaceAll('"', '""') + '"';
  if (typeof module !== 'undefined' && module.exports) module.exports = { num, scenario, initialAssumptions, filteredItems, csvCell };
  if (typeof document === 'undefined') return;
  const $ = id => document.getElementById(id);
  const items = window.__PORTFOLIO_DATA__.items;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmt = (value, suffix = '', decimals = 1) => num(value) === null ? '—' : Number(value).toLocaleString('en-US', {minimumFractionDigits:decimals, maximumFractionDigits:decimals}) + suffix;
  const pct = v => fmt(v, '%');
  const ratio = v => num(v) === null ? null : num(v) * 100;
  const money = (value, currency = 'USD') => num(value) === null ? '—' : `${currency === 'USD' ? '$' : currency + ' '}${fmt(value, '', 2)}`;
  const metricValue = (item, field, value) => item.metric_status?.[field] && num(item[field]) === null ? '不適用' : value;
  let selected = null;
  let visible = [];
  const assumptions = new Map();
  const keys = ['bear','base','bull'];
  const labels = {bear:'保守',base:'基準',bull:'樂觀',current:'現價'};
  function drawScenarios() {
    if (!selected) return;
    const state = assumptions.get(selected.symbol);
    const results = keys.map(key => {
      state[key] = {eps:$(key+'Eps').value, pe:$(key+'Pe').value};
      const result = scenario(state[key].eps, state[key].pe, selected.price);
      $(key+'Price').textContent = money(result.target, selected.currency);
      $(key+'Return').textContent = `相對現價 ${result.change !== null && result.change > 0 ? '+' : ''}${pct(result.change)}`;
      return {key, ...result};
    });
    const targets = results.map(r => r.target);
    $('scenarioWarning').textContent = targets.some(t => t === null) ? '請填入大於 0 的 EPS 與 P/E；缺值、零或負盈餘不使用本益比推算。' : targets[0] > targets[1] || targets[1] > targets[2] ? '目前情境價格未依保守 → 基準 → 樂觀遞增，請檢查假設。' : '';
    const bars = [...results, {key:'current',target:positive(selected.price)}];
    const maximum = Math.max(...bars.map(r=>r.target || 0), 1);
    $('scenarioChart').innerHTML = bars.map(r=>`<div class="chart-row ${r.key}"><span>${labels[r.key]}</span><div class="chart-track"><div class="chart-fill" style="width:${r.target === null ? 0 : r.target/maximum*100}%"></div></div><strong>${esc(money(r.target, selected.currency))}</strong></div>`).join('');
  }
  function openCompany(symbol, focus = false) {
    selected = items.find(i=>i.symbol === symbol) || null;
    $('researchPanel').hidden = !selected;
    if (!selected) return;
    const i = selected;
    $('companyTitle').textContent = i.symbol;
    $('companySector').textContent = `${i.sector} / ${i.industry || '產業細分類待補'}`;
    $('companyName').textContent = i.name;
    $('companyPrice').textContent = money(i.price, i.currency);
    $('positionWeight').textContent = `持倉權重 ${pct(i.portfolio_weight)}`;
    $('dataStatus').textContent = ({cached:'快取資料', live:'最近取得快照', partial:'部分資料', unavailable:'資料尚未取得'})[i.data_status] || '資料狀態待核對';
    $('businessDescription').textContent = i.business_description || '公司業務描述待補。';
    const metrics = [['TTM P/E',fmt(i.trailing_pe,'×')],['Forward P/E',fmt(i.forward_pe,'×')],['ROA',pct(i.roa)],['ROE',pct(i.roe)],['營收年增率',pct(ratio(i.revenue_growth))],['淨利率',pct(ratio(i.profit_margin))],['FCF 殖利率',pct(i.fcf_yield)],['隱含 EPS 差異',pct(i.implied_eps_change)]];
    const fields = ['trailing_pe','forward_pe','roa','roe','revenue_growth','profit_margin','fcf_yield','implied_eps_change'];
    $('metricGrid').innerHTML = metrics.map(([label,value],index)=>`<div class="metric"><dl><dt>${label}</dt><dd title="${esc(i.metric_status?.[fields[index]] || '')}">${metricValue(i, fields[index], value)}</dd></dl></div>`).join('');
    const peers = items.filter(p=>p.sector===i.sector && positive(p.forward_pe)!==null).map(p=>p.forward_pe).sort((a,b)=>a-b);
    const middle = Math.floor(peers.length/2);
    const median = peers.length % 2 ? peers[middle] : (peers[middle-1]+peers[middle])/2;
    $('peerContext').textContent = peers.length >= 3 && i.sector !== '其他' ? `持倉中的${i.sector}樣本（含本股）共 ${peers.length} 檔有效 Forward P/E，中位數 ${fmt(median,'×')}。僅供持股內比較，非市場同業基準。` : '同產業持股有效樣本不足三檔，暫不顯示中位數。請搭配完整同業資料研究。';
    $('epsSource').textContent = `參考 EPS：${money(i.scenario_eps, i.currency)}。${i.scenario_eps === null ? '尚無可用正值，請自行輸入。' : i.eps_source}。EPS 與股價使用相同幣別 ${i.currency || 'USD'}。`;
    if (!assumptions.has(i.symbol)) assumptions.set(i.symbol, initialAssumptions(i));
    for (const key of keys) for (const field of ['eps','pe']) $(key+(field==='eps'?'Eps':'Pe')).value = assumptions.get(i.symbol)[key][field];
    drawScenarios();
    const notes = i.research_notes.length ? i.research_notes : ['未觸發資料與指標提示；仍需核對財報期間、盈餘可持續性與估值假設。'];
    $('researchNotes').innerHTML = notes.map(n=>`<li>${esc(n)}</li>`).join('');
    const reviewed = i.reviewed_buyback;
    const rows = reviewed ? [
      ['已核對回購額度', reviewed.authorization],
      [reviewed.actual_label || '可得近四季實際執行', money(reviewed.actual ?? i.buyback_ttm, reviewed.actual_currency || i.financial_currency || i.currency)],
      ['執行資料期間', reviewed.actual_period || i.buyback_period_end || '來源未提供'],
      ['計畫期限／狀態', reviewed.expiry],
      ['核對文件期末', i.reviewed_source.period],
      ['人工核對日期', i.reviewed_at]
    ] : [['最新授權規模',money(i.buyback_authorized_amount)],['近四季實際執行',money(i.buyback_ttm,i.financial_currency || i.currency)],['最新資料期間',i.buyback_period_end || '—'],['計畫期限',i.buyback_program_expiry || '—']];
    $('buybackDetails').innerHTML = rows.map(([k,v])=>`<div><dt>${k}</dt><dd>${esc(v)}</dd></div>`).join('');
    $('buybackSource').replaceChildren();
    if (reviewed) {
      const note = document.createElement('span'); note.textContent = (i.reviewed_data_stale ? '歷史核對資料，需重新查核。' : '') + reviewed.note + ' '; $('buybackSource').append(note);
    }
    const sourceUrl = i.reviewed_source?.url || i.buyback_program_source_url;
    if (sourceUrl && /^https:\/\/www\.sec\.gov\//.test(sourceUrl)) {
      const link = document.createElement('a'); link.href=sourceUrl;link.target='_blank';link.rel='noopener noreferrer';link.textContent=`SEC ${i.reviewed_source?.form || i.buyback_program_form || '文件'} · ${i.reviewed_source?.filed || i.buyback_program_filed || '日期待補'} ↗`;$('buybackSource').append(link);
    } else $('buybackSource').textContent='尚無可核對的回購授權文件。';
    const sources = [{label:'Yahoo Finance：報價、估值與財務指標',url:`https://finance.yahoo.com/quote/${encodeURIComponent(i.symbol)}/key-statistics/`,period:`最近財報期末 ${i.fundamental_period || '來源未提供'}；各指標可能採 TTM 或預估期間`,note:`擷取時間 ${i.fetched_at || window.__PORTFOLIO_DATA__.generated_at}`}];
    if (i.fcf_source) sources.push(i.fcf_source);
    if (i.reviewed_source) sources.push({label:'SEC：已核對回購計畫與財報',url:i.reviewed_source.url,period:`文件期末 ${i.reviewed_source.period}；申報 ${i.reviewed_source.filed}`,note:`人工核對 ${i.reviewed_at}`});
    $('dataSources').innerHTML = sources.map(s=>`<li><a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.label)} ↗</a><small>${esc(s.period)} · ${esc(s.note || '')}</small></li>`).join('');
    $('quoteLink').href = `https://finance.yahoo.com/quote/${encodeURIComponent(i.symbol)}/`;
    markSelection();
    if (focus) { $('researchPanel').scrollIntoView({behavior:'smooth',block:'start'});$('companyTitle').focus({preventScroll:true}); }
  }
  function markSelection() {
    document.querySelectorAll('[data-company]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.company===selected?.symbol)));
    document.querySelectorAll('#comparisonBody tr').forEach(row=>row.classList.toggle('selected',row.dataset.symbol===selected?.symbol));
  }
  function filter() {
    visible = filteredItems(items,$('searchInput').value,$('sectorFilter').value,$('attentionFilter').checked,$('sortSelect').value);
    $('resultCount').textContent=`${visible.length} / ${items.length} 檔符合條件`;
    $('emptyState').hidden=visible.length>0;
    $('companyList').innerHTML=visible.map(i=>`<button type="button" class="company-option" data-company="${esc(i.symbol)}"><span><strong>${esc(i.symbol)}</strong><small>${esc(i.name)}</small></span><span class="list-pe">${fmt(i.forward_pe,'×')}<small>Forward P/E</small></span></button>`).join('');
    $('comparisonBody').innerHTML=visible.length ? visible.map(i=>`<tr data-symbol="${esc(i.symbol)}"><td><button type="button" data-company="${esc(i.symbol)}">${esc(i.symbol)}</button><span class="sector">${esc(i.sector)}</span></td><td title="${esc(i.metric_status?.trailing_pe || '')}">${metricValue(i,'trailing_pe',fmt(i.trailing_pe,'×'))}</td><td>${fmt(i.forward_pe,'×')}</td><td>${pct(i.roa)}</td><td title="${esc(i.metric_status?.roe || '')}">${metricValue(i,'roe',pct(i.roe))}</td><td>${pct(ratio(i.revenue_growth))}</td><td>${pct(ratio(i.profit_margin))}</td><td>${pct(i.fcf_yield)}</td><td>${i.research_notes.length} 項</td></tr>`).join('') : '<tr><td colspan="9">沒有符合條件的公司，請調整篩選。</td></tr>';
    if (!visible.some(i=>i.symbol===selected?.symbol)) openCompany(visible[0]?.symbol);
    else markSelection();
  }
  document.addEventListener('click',event=>{const button=event.target.closest('[data-company]');if(button)openCompany(button.dataset.company, true);});
  $('searchInput').addEventListener('input',filter);
  for(const id of ['sectorFilter','attentionFilter','sortSelect'])$(id).addEventListener('change',filter);
  $('clearFilters').addEventListener('click',()=>{$('searchInput').value='';$('sectorFilter').value='all';$('attentionFilter').checked=false;filter();});
  keys.forEach(key=>['Eps','Pe'].forEach(field=>$(key+field).addEventListener('input',drawScenarios)));
  $('resetScenario').addEventListener('click',()=>{if(selected){assumptions.delete(selected.symbol);openCompany(selected.symbol);}});
  $('exportButton').addEventListener('click',()=>{
    const rows=[['代號','公司','產業','TTM P/E','Forward P/E','ROA %','ROE %','營收年增率 %','淨利率 %','FCF 殖利率 %','研究待辦','快照時間','FCF 來源','回購額度','回購核對來源'],...visible.map(i=>[i.symbol,i.name,i.sector,i.trailing_pe ?? i.metric_status?.trailing_pe,i.forward_pe,i.roa,i.roe ?? i.metric_status?.roe,ratio(i.revenue_growth),ratio(i.profit_margin),i.fcf_yield,i.research_notes.join('；'),window.__PORTFOLIO_DATA__.generated_at,i.fcf_source?.url || i.quote_url,i.reviewed_buyback?.authorization,i.reviewed_source?.url])];
    const blob=new Blob(['\ufeff'+rows.map(r=>r.map(csvCell).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8;'});
    const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='holdings-research.csv';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
  filter();
})();
