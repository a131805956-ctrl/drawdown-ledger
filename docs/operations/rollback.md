---
title: 回復應用程式版本
contentType: Troubleshooting
---

# 回復應用程式版本

本頁說明新版本發生問題時的回復順序。先保護研究資料，再切換原始碼與服務。

## 判斷是否需要回復

符合任一情況時停止新版本：

- API 無法通過 `/api/v1/data/health`
- 回測結果無法重現既有正式結果
- 資料 schema 或報告 lineage 驗證失敗
- Funnel 改動非 `/drawdown-ledger` 路由
- CI、PowerShell 或隱私掃描失敗

## 建立故障現場備份

如果服務仍可安全讀取資料，先執行：

```powershell
.\scripts\Backup.ps1 -Name failed-release-20260726
.\scripts\Stop.ps1
```

不要使用 `git reset --hard`。請在新目錄檢出舊標籤，保留故障版本供比對。

## 在新目錄檢出舊版本

列出版本：

```powershell
gh release list
git tag --list "v*"
```

建立獨立 worktree：

```powershell
git worktree add ..\drawdown-ledger-v0.1.0 v0.1.0
Set-Location ..\drawdown-ledger-v0.1.0
```

先執行乾跑：

```powershell
.\scripts\Start.ps1 -DryRun
.\scripts\Open-Funnel.ps1 -DryRun
```

## 還原相容資料

若新版本已修改資料，使用升級前備份：

```powershell
.\scripts\Start.ps1 -SkipDataUpdate
.\scripts\Stop.ps1
.\scripts\Restore.ps1 `
  -BackupPath D:\drawdown-backups\before-upgrade-20260726 `
  -DryRun
.\scripts\Restore.ps1 `
  -BackupPath D:\drawdown-backups\before-upgrade-20260726
```

重新啟動後檢查健康端點與一筆已知回測。

## 切回 Funnel

確認舊版本本機服務健康，再執行：

```powershell
.\scripts\Open-Funnel.ps1 -ReplaceExisting
```

腳本只替換 `/drawdown-ledger`。完成後用 `tailscale funnel status --json` 確認其他路徑未改變。

## 回復 GitHub Pages

建立一個還原 PR，將 `main` 的應用程式變更反向提交。不要直接改寫 `main` 歷史。

合併後，Pages 工作流程會部署還原版本：

```powershell
gh run list --workflow Pages --limit 1
gh run watch
```

## 完成事故紀錄

記錄故障版本、影響範圍、資料備份、回復版本、驗證結果與後續測試。若問題涉及資料或報告可信度，撤下受影響的 published report。
