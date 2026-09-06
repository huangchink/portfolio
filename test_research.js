const {test} = require('node:test');
const assert = require('node:assert/strict');
const {scenario, initialAssumptions, filteredItems, csvCell} = require('./static/research.js');
test('EPS times multiple and relative price change',()=>{
  assert.deepEqual(scenario(6,25,120),{target:150,change:25});
  assert.deepEqual(scenario(6,25,null),{target:150,change:null});
});
test('missing, nonpositive and overflowing inputs are unavailable',()=>{
  for(const eps of ['',null,undefined,-1,0,NaN,Infinity]) assert.equal(scenario(eps,20,100).target,null);
  assert.equal(scenario(1e308,20,100).target,null);
  assert.equal(scenario(3,'',100).target,null);
});
test('initial assumptions disclose compounded sensitivity and independent objects',()=>{
  const first=initialAssumptions({scenario_eps:10,forward_pe:20});
  assert.equal(scenario(first.bear.eps,first.bear.pe,200).target,128);
  assert.equal(scenario(first.base.eps,first.base.pe,200).target,200);
  assert.equal(scenario(first.bull.eps,first.bull.pe,200).target,288);
  first.base.eps='99';
  assert.equal(initialAssumptions({scenario_eps:10,forward_pe:20}).base.eps,'10');
  assert.equal(initialAssumptions({scenario_eps:null,forward_pe:null}).base.eps,'');
});
test('combined search sector and attention filtering; missing values sort last',()=>{
  const items=[{symbol:'A',name:'Alpha',sector:'科技',forward_pe:null,research_notes:[]},{symbol:'B',name:'Beta',sector:'科技',forward_pe:12,research_notes:['待補']},{symbol:'C',name:'Capital',sector:'金融',forward_pe:8,research_notes:[]}];
  assert.deepEqual(filteredItems(items,'','all',false,'forward_pe').map(x=>x.symbol),['C','B','A']);
  assert.deepEqual(filteredItems(items,'bEt','科技',true,'symbol').map(x=>x.symbol),['B']);
  assert.equal(filteredItems(items,'xyz','all',false,'symbol').length,0);
  assert.equal(items[0].symbol,'A');
});
test('CSV escapes quotes and formula-like content',()=>{
  assert.equal(csvCell('a"b'),'"a""b"');
  assert.equal(csvCell('=1+1'),'"\'=1+1"');
  assert.equal(csvCell(null),'""');
});
const fs = require('node:fs');
const vm = require('node:vm');
test('page wiring supports selection, per-company assumptions, filters and empty data',()=>{
  const template=fs.readFileSync('./templates/fundamentals.html','utf8');
  function run(items) {
    const elements=new Map([...template.matchAll(/id="([A-Za-z][A-Za-z0-9]*)"/g)].map(m=>[m[1],{value:'',checked:false,hidden:false,innerHTML:'',textContent:'',events:{},addEventListener(event,fn){this.events[event]=fn},replaceChildren(){},append(){},scrollIntoView(){},focus(){}}]));
    for(const key of ['bear','base','bull']) for(const suffix of ['Eps','Pe','Price','Return']) elements.set(key+suffix,{value:'',textContent:'',events:{},addEventListener(event,fn){this.events[event]=fn}});
    elements.get('sectorFilter').value='all';elements.get('sortSelect').value='symbol';
    const events={};const document={getElementById:id=>{assert.ok(elements.has(id),`missing element: ${id}`);return elements.get(id)},querySelectorAll:()=>[],addEventListener:(event,fn)=>events[event]=fn,createElement:()=>({}),body:{append(){}}};
    vm.runInNewContext(fs.readFileSync('./static/research.js','utf8'),{document,window:{__PORTFOLIO_DATA__:{items,generated_at:'2026-09-05'}},console});
    return {elements,events};
  }
  const make=symbol=>({symbol,name:symbol,sector:'科技',price:120,forward_pe:20,scenario_eps:6,currency:'USD',research_notes:[],eps_source:'test',data_status:'cached',roe:null,metric_status:{roe:'不適用：股東權益非正值'},reviewed_buyback:{authorization:'120 million shares',expiry:'not disclosed',note:'Reviewed against filing'},reviewed_source:{url:'https://www.sec.gov/Archives/example.htm',period:'2026-06-30',filed:'2026-08-01',form:'10-Q'},reviewed_at:'2026-09-06'});
  const {elements,events}=run([make('A'),make('B')]);
  assert.equal(elements.get('companyTitle').textContent,'A');
  assert.equal(elements.get('basePrice').textContent,'$120.00');
  assert.ok(elements.get('metricGrid').innerHTML.includes('不適用'));
  assert.ok(elements.get('buybackDetails').innerHTML.includes('120 million shares'));
  assert.ok(elements.get('dataSources').innerHTML.includes('https://www.sec.gov/Archives/example.htm'));
  elements.get('baseEps').value='8';elements.get('baseEps').events.input();
  assert.equal(elements.get('basePrice').textContent,'$160.00');
  const choose=symbol=>events.click({target:{closest:()=>({dataset:{company:symbol}})}});
  choose('B');assert.equal(elements.get('baseEps').value,'6');
  choose('A');assert.equal(elements.get('baseEps').value,'8');
  elements.get('resetScenario').events.click();assert.equal(elements.get('baseEps').value,'6');
  elements.get('searchInput').value='nothing';elements.get('searchInput').events.input();
  assert.equal(elements.get('emptyState').hidden,false);
  assert.equal(elements.get('researchPanel').hidden,true);
  elements.get('clearFilters').events.click();assert.equal(elements.get('researchPanel').hidden,false);
  assert.equal(run([]).elements.get('researchPanel').hidden,true);
});
