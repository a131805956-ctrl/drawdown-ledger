---
title: 部署本機服務、Funnel 與 Pages
contentType: How-to
---

# 部署本機服務、Funnel 與 Pages

本頁說明如何啟動本機服務、開啟 Tailscale Funnel，以及部署 GitHub Pages 靜態備援。操作對象是 Windows 維護者。

## 準備環境

先安裝以下工具：

- Python 3.11
- Node.js 22
- Git
- PowerShell 7
- Tailscale 1.98 或更新版本

確認 PowerShell 可找到命令：

```powershell
python --version
node --version
git --version
pwsh --version
tailscale version
```

## 啟動本機服務

在專案根目錄執行啟動腳本：

```powershell
.\scripts\Start.ps1
```

腳本會建立 `.venv`、安裝 Python 套件、執行 `npm ci`、建置 React 介面、啟動 `127.0.0.1:8787`，再更新前一個月的資料。啟動完成後開啟 `http://127.0.0.1:8787/`。

若 Yahoo 更新失敗，腳本回傳 `running-degraded` 並繼續使用舊快取。請到 `http://127.0.0.1:8787/api/v1/data/health` 確認政策截止日與實際最後交易日。

## 開啟 HTTPS 公開網址

先確認本機服務健康，再執行：

```powershell
.\scripts\Open-Funnel.ps1
```

預設公開路徑是 `/drawdown-ledger`。腳本會拒絕不屬於本專案的既有路由。只有你確認要替換同一路徑時，才可加入 `-ReplaceExisting`。

```powershell
.\scripts\Open-Funnel.ps1 -ReplaceExisting
```

不要對 Tailscale 執行全域 `reset`。Drawdown Ledger 只管理 `/drawdown-ledger`，並保留其他 Funnel 路徑。

## 停止服務

執行：

```powershell
.\scripts\Stop.ps1
```

腳本先驗證目前程序的執行檔、完整參數、專案路徑與連接埠。驗證失敗時，腳本拒絕終止程序。Funnel 還原也會驗證路徑、HTTPS 連接埠、代理與目標。

若你要保留公開路由，只停止本機程序：

```powershell
.\scripts\Stop.ps1 -KeepFunnel
```

## 部署 GitHub Pages

`.github/workflows/pages.yml` 只在 `main` 更新或手動觸發時部署。工作流程會：

1. 掃描靜態示例，逐一驗證 `reports/published` 的 canonical bundles
2. 以 `/drawdown-ledger/` 為基底建置靜態模式
3. 建立公開報告清單與 `404.html`，支援報告入口及直接開啟深層路徑
4. 上傳 `apps/web/dist`
5. 部署到 `github-pages` 環境

先在 GitHub Repository Settings 的 **Pages** 選擇 **GitHub Actions**。合併交付 PR 後，也可手動執行：

```powershell
gh workflow run Pages
gh run watch
```

GitHub Pages 沒有本機 API。它只顯示固定示例與已通過隱私檢查的報告；
報告入口是 `/drawdown-ledger/reports/index.html`。

## 驗證部署

依序檢查：

```powershell
Invoke-RestMethod http://127.0.0.1:8787/api/v1/data/health
tailscale funnel status --json
gh run list --workflow Pages --limit 1
```

瀏覽器驗證本機、Funnel 與 Pages 都能載入市場總覽、歷史證據及報告頁。

設計與安全約束記錄在 [平台設計規格](../superpowers/specs/2026-07-26-etf-drawdown-research-platform-design.md)。
