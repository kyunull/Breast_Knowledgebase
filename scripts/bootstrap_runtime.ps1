[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [switch]$Install
)

$ErrorActionPreference = "Stop"
$resolvedRequiredRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..") -ErrorAction Stop).Path

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = $resolvedRequiredRoot
}

if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) {
    throw "ProjectRoot must resolve to $resolvedRequiredRoot; received a non-directory path: $ProjectRoot"
}

$resolvedRoot = (Resolve-Path -LiteralPath $ProjectRoot -ErrorAction Stop).Path
if (-not [string]::Equals(
    $resolvedRoot,
    $resolvedRequiredRoot,
    [System.StringComparison]::OrdinalIgnoreCase
)) {
    throw "ProjectRoot must resolve to $resolvedRequiredRoot; received: $resolvedRoot"
}

$dataDir = Join-Path $resolvedRoot "data"
$runtimeCache = Join-Path $dataDir "runtime_cache"
$wheelhouse = Join-Path $dataDir "vendor_wheels"
$tempDir = Join-Path $runtimeCache "tmp"
$pipCache = Join-Path $runtimeCache "pip_cache"
$modelCache = Join-Path $dataDir "model_cache"
$hfHome = $modelCache
$huggingfaceHubCache = $modelCache
$transformersCache = Join-Path $hfHome "transformers"
$sentenceTransformersHome = Join-Path $modelCache "sentence_transformers"
$torchHome = Join-Path $modelCache "torch"
$venvPython = Join-Path $resolvedRoot ".venv\Scripts\python.exe"

foreach ($directory in @(
    $runtimeCache,
    $wheelhouse,
    $tempDir,
    $pipCache,
    $hfHome,
    $huggingfaceHubCache,
    $transformersCache,
    $sentenceTransformersHome,
    $torchHome
)) {
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "Expected project virtual environment at $venvPython. Create it under the project root before bootstrapping."
}

$env:TEMP = $tempDir
$env:TMP = $tempDir
$env:PIP_CACHE_DIR = $pipCache
$env:HF_HOME = $hfHome
$env:HUGGINGFACE_HUB_CACHE = $huggingfaceHubCache
$env:TRANSFORMERS_CACHE = $transformersCache
$env:SENTENCE_TRANSFORMERS_HOME = $sentenceTransformersHome
$env:TORCH_HOME = $torchHome
$env:HF_HUB_DISABLE_XET = "1"
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"

& $venvPython -m pip download --only-binary=:all: --dest $wheelhouse ".[dev]"
if ($LASTEXITCODE -ne 0) {
    throw "Wheel download failed; no installation was attempted."
}

& $venvPython (Join-Path $resolvedRoot "scripts\verify_wheelhouse.py") $wheelhouse
if ($LASTEXITCODE -ne 0) {
    throw "Wheel verification failed; refusing installation."
}

if ($Install) {
    & $venvPython -m pip install --no-index --find-links $wheelhouse ".[dev]"
    if ($LASTEXITCODE -ne 0) {
        throw "Verified offline installation failed."
    }
    & $venvPython -m pip check
    if ($LASTEXITCODE -ne 0) {
        throw "pip check found broken requirements."
    }
}
