# Instala la ejecución diaria de job-agents en el Programador de tareas de Windows.
# Ejecutar una vez en PowerShell:  powershell -ExecutionPolicy Bypass -File .\instalar_tarea.ps1
# - Todos los días a las 9:30.
# - Si el PC estaba apagado a esa hora, se ejecuta en cuanto se encienda (StartWhenAvailable).
# - Despierta el PC si está en suspensión (WakeToRun).
# - Se ejecuta en tu sesión de usuario: Chrome necesita tu sesión iniciada.

$bat = Join-Path $PSScriptRoot "diario.bat"
$accion = New-ScheduledTaskAction -Execute $bat -WorkingDirectory $PSScriptRoot
$disparador = New-ScheduledTaskTrigger -Daily -At 9:30am
$ajustes = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 3)
Register-ScheduledTask -TaskName "job-agents diario" -Action $accion -Trigger $disparador `
    -Settings $ajustes -Description "Busca ofertas, adapta CVs, postula y envía espontáneas" -Force

# Abrir Chrome al iniciar sesión en Windows (para que la extensión esté lista a las 9:30)
$chrome = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
            "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
            "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($chrome) {
    $acceso = Join-Path ([Environment]::GetFolderPath("Startup")) "Chrome.lnk"
    $ws = New-Object -ComObject WScript.Shell
    $lnk = $ws.CreateShortcut($acceso); $lnk.TargetPath = $chrome; $lnk.Save()
    Write-Host "Chrome se abrirá al iniciar sesión."
}
Get-ScheduledTask -TaskName "job-agents diario" | Get-ScheduledTaskInfo | Select-Object NextRunTime
