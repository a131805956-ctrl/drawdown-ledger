# Drawdown Ledger｜回撤帳本

Drawdown Ledger 是本機優先的指數型與槓桿 ETF 研究平台。它把回撤事件、次日開盤結果、現金庫加碼與樣本外最佳化放在同一套可追溯流程中。平台不提供即時喊單，也不保證未來報酬。

## 研究標的

平台內建 6 個指數家族：

| 家族 | 1× | 2× | 3× |
| --- | --- | --- | --- |
| 台灣 50 | 0050 | 00631L | 不適用 |
| 台灣加權 | 006204 | 00685L | 不適用 |
| NASDAQ-100 | QQQ | QLD | TQQQ |
| S&P 500 | SPY | SSO | UPRO |
| 道瓊工業 | DIA | DDM | UDOW |
| Russell 2000 | IWM | UWM | URTY |

台灣市場不納入台灣掛牌的美國指數 ETF。槓桿標的以原型指數或 1× 原型判定回撤，再以實際 ETF 的次一交易日開盤價執行。

## 核心分析

平台把一句投資判斷拆成可驗證欄位：

> 如果原型指數從前高回撤 30% 後於次一交易日買進，在過去 N 次獨立事件中，一年後平均報酬、勝率、V 轉次數與仍未獲利次數分別是多少？

分析同時保留以下證據：

- 獨立回撤事件數 `N_episode`
- 每日重疊樣本數 `N_day`
- 前瞻總報酬、勝率信賴區間與最差 5% 結果
- 最大不利變動（MAE）、最大有利變動（MFE）與恢復前高時間
- 實際槓桿 ETF 與上市前合成壓力序列
- 每月現金投入、年成長率、暫停、恢復與獎金事件
- 股息留在現金庫或次一交易日開盤再投入
- 嚴格創新高後重置觸發資格，但不補滿現金
- 不賣出策略、定期定額與原型定期定額基準
- Walk-forward 樣本外評估、鄰域穩定性與 Pareto 候選

## 在 Windows 啟動

先安裝 Python 3.11、Node.js 22、Git 與 PowerShell 7。首次啟動會建立專案 `.venv`、安裝套件、建置介面、啟動本機服務並更新資料。

```powershell
Set-Location C:\path\to\drawdown-ledger
.\scripts\Start.ps1
```

瀏覽器開啟 `http://127.0.0.1:8787/`。服務只監聽 loopback 位址，除非你明確開啟 Tailscale Funnel。

```powershell
.\scripts\Open-Funnel.ps1
```

預設公開路徑是 `/drawdown-ledger`。腳本不會重設 Funnel，也不會改寫其他公開路徑。
`Start.ps1` 會建立忽略於 Git 的 `.runtime\public-access.json`；Funnel
只在確認非本機連線需要 HTTP Basic 驗證後才會開啟。瀏覽器提示登入時，
帳號是 `drawdown`，密碼請從該本機檔案讀取，勿貼到 Issue、PR 或日誌。
直接使用 `127.0.0.1` 的本機介面不需登入。

```powershell
.\scripts\Stop.ps1
```

停止腳本只終止符合專案路徑、完整參數與監聽連接埠的程序。它只移除或還原自己擁有的 `/drawdown-ledger` 路由。

## 資料截止政策

每次更新只抓到前一個日曆月的月底。8 月 1 日執行時，政策截止日是 7 月 31 日；若該日不是交易日，快取記錄最後一個有效交易日。更新失敗時，服務保留已驗證快取並標示 `running-degraded`。

GitHub Pages 內建的 `2026-07-31` 資料是固定示例，不是即時行情。介面會把它標成靜態備援與示意研究。

## 市場資料契約

資料層保留供應商原始欄位與衍生欄位，避免用回測結果覆寫來源資料：

- `raw_open`、`raw_high`、`raw_low`、`raw_close`、`raw_dividend` 與 `raw_split_ratio` 保存來源值
- `price_*` 只做拆股調整、不含股息，用於前高與回撤訊號
- `adj_close` 或明確的持股與股息現金流，用於總報酬與策略績效
- 每次更新記錄 provider、抓取時間、政策截止日、實際最後交易日與內容雜湊
- 原型指數、可交易 ETF 與上市前合成序列分開保存，報告必須標示來源種類

## 隱私邊界

以下內容不提交 Git：

- Yahoo 市場快取與 Parquet 檔案
- SQLite 工作、策略與結果資料庫
- 私人策略、未發佈報告與 Funnel 狀態
- `.env`、執行程序狀態與本機備份

`reports/published` 只接受通過隱私、內容雜湊與跨格式語意驗證的
canonical 匯出。持續整合（CI）會逐一驗證 bundle；Pages 只會將通過者列入
公開報告清單。外部真實性邊界是受保護的 Git 提交、PR 與版本標籤，
匯出 bundle 本身不是獨立的密碼學簽章。

## Report authenticity boundary

The manifest hashes, cross-format checks, and content-addressed export ID detect
partial or accidental bundle changes. They are not cryptographic signatures
because the local exporter has no secret signing key.

Treat Git provenance as the external authenticity boundary. Verify the
report's Git commit (`git_commit`) against the reviewed branch and PR, its
successful CI run, and the expected release tag before treating a published
report as an authentic project output. A coordinated rewrite of the complete
bundle and its provenance cannot be authenticated by local hashes alone.

## 開發與驗證

Python 使用非 editable 安裝，避免中文 Windows 路徑造成 `.pth` 解碼錯誤。

```powershell
python -m pip install ".[dev]"
python -m ruff check apps/api
python -m mypy apps/api/src
python -m pytest -q
```

前端與端對端驗證：

```powershell
npm ci --prefix apps/web
npm --prefix apps/web run typecheck
npm --prefix apps/web run lint
npm --prefix apps/web run test -- --run
npm ci
npx playwright install chromium
npm run test:e2e
npm run test:e2e:static
```

## 操作文件

- [部署本機、Funnel 與 Pages](docs/operations/deployment.md)
- [備份與還原研究資料](docs/operations/backup-and-restore.md)
- [更新資料與維護服務](docs/operations/maintenance.md)
- [回復應用程式版本](docs/operations/rollback.md)
- [讓 AI 操作瀏覽器研究模式](docs/ai/browser-operation.md)

## 授權

原始碼採用 [MIT License](LICENSE)。市場資料受原始供應商條款約束，不包含在原始碼授權內。
