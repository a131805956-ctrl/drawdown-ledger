---
title: 讓 AI 操作瀏覽器研究模式
contentType: Reference
---

# 讓 AI 操作瀏覽器研究模式

本頁定義 AI 如何在不使用 API key 的情況下操作 `/ai`。所有核心欄位都有固定 `id`、`name`、`aria-label` 與 `data-ai-*` 屬性。

## 開啟研究頁

本機網址：

```text
http://127.0.0.1:8787/ai
```

Funnel 網址使用相同路徑：

```text
https://your_tailnet_name.ts.net/drawdown-ledger/ai
```

GitHub Pages 是唯讀備援，不能執行新最佳化。

## 填寫核心欄位

AI 應依下表尋找欄位：

| 目的 | Selector | 值範例 |
| --- | --- | --- |
| 指數家族 | `#ai-family-id` | `nasdaq-100` |
| 標的 | `#ai-target-symbol` | `TQQQ` |
| 開始日 | `#ai-start` | `2011-01-03` |
| 結束日 | `#ai-end` | `2026-06-30` |
| 回撤層級 | `#ai-depths` | `20, 30, 40` |
| 最小比例 | `#ai-min-ratio` | `0` |
| 最大比例 | `#ai-max-ratio` | `100` |
| 比例步長 | `#ai-ratio-step` | `10` |
| Walk-forward 分割 | `#ai-walk-forward-splits` | `3` |
| 最多候選 | `#ai-max-candidates` | `14641` |
| 單調比例 | `#ai-monotone` | checked |
| 合成壓力 | `#ai-synthetic-stress` | checked |

現金庫欄位使用 `#ai-initial-cash`、`#ai-monthly-contribution`、`#ai-annual-growth`、`#ai-cash-interest`、`#ai-minimum-episodes` 與 `#ai-dividend-policy`。

## 執行一鍵分析

AI 應照以下順序操作：

1. 開啟 `/ai`
2. 填寫範圍、網格與現金庫假設
3. 點擊 `[data-ai-action="run-optimization"]`
4. 等待工作狀態變成 `succeeded`
5. 讀取保守、平衡與積極建議
6. 讀取 Pareto 候選表
7. 核對 provenance、獨立事件數與 synthetic stress
8. 匯出設定 JSON，保存完整輸入

不要以頁面載入動畫判定完成。請等待結果標題「三種可執行方案」出現。

## 匯入與匯出 JSON

先點擊 `[data-ai-action="export-configuration"]` 取得 canonical request。修改前保留原檔。

匯入時使用：

```css
[data-ai-action="import-configuration"]
```

頁面會驗證 JSON。若欄位錯誤，先修正設定，不要略過限制。

## 評估候選比例

AI 不應只挑最高樣本內報酬。至少比較：

- `stability_adjusted_xirr`
- `worst_5_return`
- `early_depletion_rate`
- `longest_trap_days`
- `neighbor_count`
- `synthetic_stress_pass`
- `walk_forward_eligible`

若獨立事件不足，結果只能標成探索。AI 必須在結論中揭露樣本數與限制。

## 可直接交給 AI 的操作指令

```text
開啟 Drawdown Ledger 的 /ai。
選擇 nasdaq-100 與 TQQQ。
使用 20、30、40% 回撤層級。
以 10% 步長窮舉單調現金比例。
執行 3 段 walk-forward 與合成槓桿壓力測試。
完成後比較保守、平衡、積極方案。
列出穩定調整 XIRR、最差 5%、提早耗盡率與最長套牢期。
不要把 exploration-only 結果寫成正式建議。
匯出並保存本次設定 JSON。
```

## PowerShell 替代操作

若 AI 能讀寫本機檔案，也可執行：

```powershell
.\scripts\Analyze.ps1 `
  -Config .\.runtime\research-request.json `
  -Endpoint optimization `
  -OutFile .\.runtime\analysis-response.json
```

此命令仍使用本機 API，不需要外部模型金鑰。
