# Avvio locale del backend Equity Research.
# Legge le variabili da .env (il codice NON usa python-dotenv, quindi le carichiamo qui),
# poi lancia uvicorn su http://localhost:8000, come in produzione su Render.
#
#   .\start-local.ps1            avvio normale (come Render)
#   .\start-local.ps1 -Reload    con auto-reload sui cambi di file (dev)

param([switch]$Reload)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$envFile = Join-Path $PSScriptRoot ".env"
if (-not (Test-Path $envFile)) {
    Write-Error "File .env non trovato in $PSScriptRoot. Crealo con i valori delle chiavi."
    exit 1
}

Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if ($line -eq "" -or $line.StartsWith("#")) { return }
    $idx = $line.IndexOf("=")
    if ($idx -lt 1) { return }
    $name = $line.Substring(0, $idx).Trim()
    $value = $line.Substring($idx + 1).Trim()
    if ($value.Length -ge 2 -and $value.StartsWith('"') -and $value.EndsWith('"')) {
        $value = $value.Substring(1, $value.Length - 2)
    }
    if ($value -ne "") {
        [Environment]::SetEnvironmentVariable($name, $value, "Process")
        Write-Host "  env: $name impostata"
    }
}

$py = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
Write-Host "`nAvvio backend su http://localhost:8000 (docs: http://localhost:8000/docs)`n"
$uvicornArgs = @("-m", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000")
if ($Reload) { $uvicornArgs += "--reload" }
& $py @uvicornArgs
