# Fundamentals Desk

個人投資組合基本面分析網站，集中呈現：

- Trailing P/E 與 Forward P/E
- ROA（資產報酬率）
- 依個人平均成本計算的持倉 ROI
- 最近四個已揭露季度是否有股票回購，並提供規模、資料期間與計畫期限提示
- 現價距離拆股調整後歷史最高價（ATH）的百分比

行情與財務資料由 Yahoo Finance 取得，回購授權規模與期限則從最新 SEC 定期報告擷取；GitHub Actions 每日產生靜態快照並部署至 GitHub Pages。

## 本機執行

```bash
pip install -r requirements.txt
python fundamentals_app.py --serve
```

開啟 <http://127.0.0.1:5000/>。

## 產生靜態網站

```bash
python fundamentals_app.py --output docs/index.html
```

若即時來源暫時無法取得個別股票資料，產生器會沿用最近一次成功快取，並在資料中標記為 cached。

> 本網站僅供個人研究，不構成投資建議。ROI 未計入股息、稅費與匯率。
