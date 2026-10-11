<#
.SYNOPSIS
  teams-notifier için Windows Görev Zamanlayıcı görevi kurar veya kaldırır.

.DESCRIPTION
  Günde bir kez (varsayılan 09:00) `teams-notifier run` çalıştırır.
  - Bilgisayar o saatte kapalıysa, açıldığında bir kez çalışır.
  - Ağ yoksa ağ gelene kadar bekler.
  - Konsol penceresi açmaz (pythonw).
  - Yönetici hakkı gerektirmez; mevcut kullanıcı olarak çalışır
    (şifreli token önbelleği kullanıcıya özeldir).

.EXAMPLE
  .\install_task.ps1                 # her gün 09:00
  .\install_task.ps1 -Time 08:30     # saati değiştir (yeniden çalıştırmak görevi günceller)
  .\install_task.ps1 -Uninstall      # görevi kaldır
#>
param(
    [string]$Time = "09:00",
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$TaskName = "teams-notifier"

if ($Uninstall) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Görev kaldırıldı: $TaskName"
    } else {
        Write-Host "Görev zaten yok: $TaskName"
    }
    return
}

if ($Time -notmatch '^([01]\d|2[0-3]):[0-5]\d$') {
    throw "Saat HH:mm biçiminde olmalı (örn. 09:00)."
}

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pythonw)) {
    throw "$pythonw bulunamadı. Önce kurulumu yap (README: Kurulum)."
}

$action = New-ScheduledTaskAction -Execute $pythonw -Argument "-m teams_notifier run" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null

Write-Host "Görev kuruldu: her gün $Time (kaçırılırsa bilgisayar açılınca çalışır)."
Write-Host "Hemen denemek için: Start-ScheduledTask -TaskName $TaskName"
Write-Host "Kaldırmak için:     .\scripts\install_task.ps1 -Uninstall"
