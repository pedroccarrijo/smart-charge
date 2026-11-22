$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
Push-Location $workspace
try {
    $credentialLines = & docker compose run --rm --no-deps db-init python -m services.show_credentials
    if ($LASTEXITCODE -ne 0) { throw 'Nao foi possivel ler as credenciais locais.' }
    $directory = Join-Path $workspace 'secrets'
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    $outputPath = Join-Path $directory 'usuarios-demo.txt'
    [System.IO.File]::WriteAllLines($outputPath, [string[]]$credentialLines, [System.Text.UTF8Encoding]::new($false))
    Write-Output "Credenciais salvas em: $outputPath"
} finally {
    Pop-Location
}
