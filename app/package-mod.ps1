param(
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"
$modDirectory = Join-Path $PSScriptRoot "factorio-mod"
$infoPath = Join-Path $modDirectory "info.json"

if (-not (Test-Path -LiteralPath $infoPath)) {
    throw "Factorio mod metadata was not found at $infoPath"
}

$metadata = Get-Content -LiteralPath $infoPath -Raw | ConvertFrom-Json
if ([string]::IsNullOrWhiteSpace($metadata.name) -or [string]::IsNullOrWhiteSpace($metadata.version)) {
    throw "info.json must contain name and version"
}

if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path (Split-Path -Parent $PSScriptRoot) "$($metadata.name)_$($metadata.version).zip"
}

$outputDirectory = Split-Path -Parent $OutputPath
if ($outputDirectory) {
    New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
}

$tempPath = Join-Path ([System.IO.Path]::GetTempPath()) "$($metadata.name)_$($metadata.version)_$([guid]::NewGuid()).zip"
$stagingPath = Join-Path ([System.IO.Path]::GetTempPath()) "$($metadata.name)_$($metadata.version)_$([guid]::NewGuid())"
try {
    $stagedModDirectory = Join-Path $stagingPath $metadata.name
    New-Item -ItemType Directory -Path $stagedModDirectory -Force | Out-Null
    $archiveInputs = Get-ChildItem -LiteralPath $modDirectory -Force | Where-Object {
        $_.Name -notin @("__pycache__", "zips")
    }
    foreach ($archiveInput in $archiveInputs) {
        Copy-Item -LiteralPath $archiveInput.FullName -Destination $stagedModDirectory -Recurse -Force
    }
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::Open($tempPath, [System.IO.Compression.ZipArchiveMode]::Create)
    try {
        foreach ($file in Get-ChildItem -LiteralPath $stagedModDirectory -File -Recurse) {
            $relativePath = $file.FullName.Substring($stagingPath.Length + 1).Replace("\", "/")
            [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                $zip,
                $file.FullName,
                $relativePath,
                [System.IO.Compression.CompressionLevel]::Optimal
            ) | Out-Null
        }
    } finally {
        $zip.Dispose()
    }
    Move-Item -LiteralPath $tempPath -Destination $OutputPath -Force
} finally {
    Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $stagingPath -Recurse -Force -ErrorAction SilentlyContinue
}

$archive = [System.IO.Compression.ZipFile]::OpenRead($OutputPath)
try {
    $expectedInfoPath = "$($metadata.name)/info.json"
    $hasInfoPath = $archive.Entries | Where-Object {
        $_.FullName.Replace("\", "/") -eq $expectedInfoPath
    }
    if ($null -eq $hasInfoPath) {
        throw "Generated archive does not contain $($metadata.name)/info.json"
    }
} finally {
    $archive.Dispose()
}

Write-Output "Created $OutputPath"
