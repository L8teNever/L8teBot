# L8teBot Backup Restore Script (Windows/PowerShell)
# Usage: .\restore_backup.ps1 "C:\path\to\backup.zip"

param(
    [Parameter(Mandatory=$true)]
    [string]$BackupFile
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DataDir = Join-Path $ScriptDir "data"

if (-not (Test-Path $BackupFile)) {
    Write-Host "❌ Backup-Datei nicht gefunden: $BackupFile" -ForegroundColor Red
    exit 1
}

Write-Host "🔄 Stoppe Container..." -ForegroundColor Yellow
docker-compose down

Write-Host "📦 Erstelle Sicherung der aktuellen Daten..." -ForegroundColor Yellow
if (Test-Path $DataDir) {
    $BackupName = "data_backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
    Rename-Item $DataDir $BackupName
}

Write-Host "📂 Erstelle neues data Verzeichnis..." -ForegroundColor Yellow
New-Item -ItemType Directory -Path $DataDir -Force | Out-Null

Write-Host "📥 Entpacke Backup..." -ForegroundColor Yellow
$TempDir = Join-Path $env:TEMP "l8tebot_restore"
if (Test-Path $TempDir) { Remove-Item $TempDir -Recurse -Force }
Expand-Archive -Path $BackupFile -DestinationPath $TempDir

# Prüfe ob 'data' Ordner im Backup existiert
$ExtractedDataDir = Join-Path $TempDir "data"
if (Test-Path $ExtractedDataDir) {
    Write-Host "✅ Backup enthält 'data' Ordner - kopiere Inhalt..." -ForegroundColor Green
    Copy-Item -Path "$ExtractedDataDir\*" -Destination $DataDir -Recurse -Force
} else {
    Write-Host "✅ Backup ist direkt der Inhalt - kopiere alles..." -ForegroundColor Green
    Copy-Item -Path "$TempDir\*" -Destination $DataDir -Recurse -Force
}

Write-Host "🧹 Räume auf..." -ForegroundColor Yellow
Remove-Item $TempDir -Recurse -Force

Write-Host "🚀 Starte Container neu..." -ForegroundColor Yellow
docker-compose up -d

Write-Host "✅ Backup erfolgreich wiederhergestellt!" -ForegroundColor Green
Write-Host "📊 Überprüfe die Logs mit: docker-compose logs -f" -ForegroundColor Cyan
