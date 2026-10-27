param([Parameter(Mandatory=$true)][string]$PrivateDirectory)
$ErrorActionPreference = 'Stop'
$settings = Get-Content -LiteralPath (Join-Path $PrivateDirectory 'supervisor.json') -Raw | ConvertFrom-Json
$script = Join-Path $PSScriptRoot 'supervisor.py'
Start-Process -FilePath $settings.python_path -ArgumentList @(('"' + $script + '"'), '--private-dir', ('"' + $PrivateDirectory + '"')) -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
Write-Output 'Kontrolpanelets baggrundsprogram er startet. Minecraft starter kun, når der trykkes Start server.'
