param(
    [Parameter(Mandatory=$true)][string]$Archive,
    [string]$Summary = 'Opdateret modpakke.',
    [string]$PrivateDirectory = 'C:\Users\Marius\MinecraftServers\Create-Magic-Lite\panel-private',
    [string]$InstanceMetadata = 'C:\Users\Marius\curseforge\minecraft\Instances\Create & Magic Lite\minecraftinstance.json',
    [string]$ServerModsDirectory = 'C:\Users\Marius\MinecraftServers\Create-Magic-Lite\mods'
)
$ErrorActionPreference = 'Stop'
$settings = Get-Content -LiteralPath (Join-Path $PrivateDirectory 'supervisor.json') -Raw | ConvertFrom-Json
$archivePath = (Resolve-Path -LiteralPath $Archive).Path
$metadataDirectory = Join-Path $PrivateDirectory 'release-metadata'
New-Item -ItemType Directory -Path $metadataDirectory -Force | Out-Null
$metadataPath = Join-Path $metadataDirectory (([guid]::NewGuid().ToString('N')) + '.json')
& $settings.python_path (Join-Path $PSScriptRoot 'scripts\catalog_metadata.py') --instance $InstanceMetadata --archive $archivePath --server-mods $ServerModsDirectory --output $metadataPath
if ($LASTEXITCODE -ne 0) { throw 'Metadata kunne ikke kontrolleres; udgivelsen er ikke gemt.' }
& $settings.python_path (Join-Path $PSScriptRoot 'scripts\publish_pack.py') --private-dir $PrivateDirectory --archive $archivePath --metadata $metadataPath --docs-dir (Join-Path $PSScriptRoot 'docs') --summary $Summary
if ($LASTEXITCODE -ne 0) { throw 'Udgivelsen kunne ikke gemmes. Se fejlen ovenfor.' }
Write-Output 'Versionen er gemt i databasen. Modlisten, ZIP-filen og ændringshistorikken ligger klar i docs/.'
Write-Output 'Udgiv de nye docs/releases.json og docs/downloads/ filer på GitHub for at opdatere hjemmesiden.'
