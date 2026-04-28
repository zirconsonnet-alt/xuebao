param(
  [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

python (Join-Path $PSScriptRoot "check_layer_imports.py") --root $Root
exit $LASTEXITCODE

