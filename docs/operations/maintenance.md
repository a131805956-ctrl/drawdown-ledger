---
title: 更新資料與維護服務
contentType: How-to
---

# 更新資料與維護服務

本頁說明每月更新、健康檢查、報告發佈與例行驗證。每次維護都先保留可還原備份。

## 每月更新資料

服務啟動時會自動更新。你也可以手動執行：

```powershell
.\scripts\Update-Data.ps1
```

截止日取前一個日曆月月底。8 月 1 日執行時，政策截止日是 7 月 31 日。非交易日會保留政策截止日，並記錄最後有效交易日。

若要重現指定日期的政策：

```powershell
.\scripts\Update-Data.ps1 -AsOf 2026-08-01
```

更新器只請求缺少的區段。它不會每次重抓完整歷史。

## 檢查資料健康度

執行：

```powershell
$health = Invoke-RestMethod `
  http://127.0.0.1:8787/api/v1/data/health
$health.coverage | Format-Table
```

逐列檢查：

- `cached` 是 `true`
- `policy_cutoff` 符合前月月底
- `actual_last_session` 不晚於政策截止日
- 槓桿家族包含 tradable、benchmark 與 prototype proxy 角色

若更新失敗，先保留舊快取。不要刪除 `data` 後重試。

## 發佈靜態報告

先從本機 API 匯出 canonical bundle，再執行：

```powershell
.\scripts\Publish-Report.ps1 -ExportId export_id_here
```

腳本驗證 manifest、結果雜湊、schema、lineage 與隱私欄位。只有通過的 bundle 會複製到 `reports/published`。

提交前再次執行：

```powershell
python -m drawdown_lab.reports.publication reports/published
```

這個 collection 驗證器會逐一檢查每個 bundle，拒絕根目錄雜檔、
連結／reparse point、內容雜湊或跨格式語意不一致，以及任何隱私欄位。
請只加入你確認要公開的報告；CI 會再次驗證並為 Pages 產生
`reports/index.html` 清單。

## 執行例行測試

每次升級依序執行：

```powershell
python -m ruff check apps/api
python -m mypy apps/api/src
python -m pytest -q
npm --prefix apps/web run test -- --run
npm run test:e2e
npm run test:e2e:static
Invoke-Pester -Path tests/powershell
```

若任何檢查失敗，不要建立版本標籤。

## 維護 AI 批次研究

AI 操作不需要 API key。使用固定欄位與 JSON 流程，詳見 [讓 AI 操作瀏覽器研究模式](../ai/browser-operation.md)。

每次正式採用候選比例前，請確認：

- 結果是 `formal`，不是 exploration-only
- 獨立事件數符合最低門檻
- Walk-forward 樣本外結果完整
- 合成槓桿壓力測試已執行
- 最差 5%、現金提早耗盡率與最長套牢期可接受

## 維護週期

建議排程：

| 頻率 | 操作 |
| --- | --- |
| 每月 | 更新資料、檢查截止日、建立備份 |
| 每次 PR | 完成 CI、型別、E2E 與隱私掃描 |
| 每次發行 | 建立升級前備份、驗證 rollback、建立標籤 |
| 每季 | 測試備份還原、檢查 Tailscale 路由 |
