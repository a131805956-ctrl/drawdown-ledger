---
title: 備份與還原研究資料
contentType: How-to
---

# 備份與還原研究資料

本頁說明如何建立可驗證備份，以及如何在停止服務後安全還原。備份包含 `.runtime` 與 `data` 內的 SQLite、Parquet 資料。

## 建立備份

先執行一次 `Start.ps1`，確保專案 `.venv` 存在。接著執行：

```powershell
.\scripts\Backup.ps1
```

預設輸出位於 `backups\drawdown-yyyyMMdd-HHmmss`。你也可以指定磁碟與名稱：

```powershell
.\scripts\Backup.ps1 `
  -DestinationRoot D:\drawdown-backups `
  -Name before-upgrade-20260726
```

腳本使用 SQLite Backup API 建立一致快照，再驗證 SQLite `quick_check`、Parquet metadata、檔案大小與 SHA-256。`manifest.json` 記錄每個檔案。

## 預演還原

先停止服務：

```powershell
.\scripts\Stop.ps1
```

使用 `-DryRun` 驗證備份與目標，不寫入檔案：

```powershell
.\scripts\Restore.ps1 `
  -BackupPath D:\drawdown-backups\before-upgrade-20260726 `
  -DryRun
```

預演會拒絕絕對路徑、`..`、重複檔案、錯誤副檔名、雜湊不符，以及 symlink、junction 或 reparse point。

## 執行還原

預演通過後執行：

```powershell
.\scripts\Restore.ps1 `
  -BackupPath D:\drawdown-backups\before-upgrade-20260726
```

腳本先將全部檔案複製到暫存位置，再驗證雜湊與格式。安裝失敗時，它會把原檔移回目標。

## 驗證還原

重新啟動但先跳過資料更新：

```powershell
.\scripts\Start.ps1 -SkipDataUpdate
```

接著檢查：

```powershell
Invoke-RestMethod http://127.0.0.1:8787/api/v1/data/health
```

確認每個必要序列有 `cached=true`，並核對 `actual_last_session`。若資料正確，再執行 `Update-Data.ps1`。

## 備份保存原則

請保留以下版本：

- 最近 3 次成功備份
- 每次升級前的備份
- 每月資料更新後的第一份備份

備份可能包含私人策略與研究結果。不要提交 Git，也不要放入公開同步資料夾。
