# One command: setup (first time only) -> DB check -> extract -> preview images -> open the folder.
#
#   .\run.ps1                                   # sample chapter, all pages
#   .\run.ps1 "C:\path\to\book.pdf"             # your PDF, all pages
#   .\run.ps1 "C:\path\to\book.pdf" "1,5,23"    # only these pages in the preview
#
# If PowerShell blocks scripts, run:  powershell -ExecutionPolicy Bypass -File .\run.ps1

param(
    [string]$Pdf = "samples\ch04_hi.pdf",
    [string]$Pages = "all"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$py = ".venv\Scripts\python.exe"

if (-not (Test-Path $py)) {
    Write-Host "== First run: creating .venv and installing packages" -ForegroundColor Cyan
    python -m venv .venv
    & $py -m pip install -q -r requirements.txt
}
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }
if (-not (Test-Path $Pdf)) { Write-Host "PDF not found: $Pdf" -ForegroundColor Red; exit 1 }

Write-Host "`n== 1/3 Database check" -ForegroundColor Cyan
& $py -m books_layout.cli check-db
if ($LASTEXITCODE -ne 0) { Write-Host "DB not reachable (is docker running?). Continuing without it." -ForegroundColor Yellow }

Write-Host "`n== 2/3 Extract blocks" -ForegroundColor Cyan
& $py -m books_layout.cli extract $Pdf
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "`n== 3/3 Preview images (pages: $Pages)" -ForegroundColor Cyan
& $py -m books_layout.cli preview $Pdf --pages $Pages | Out-Null
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$name = [System.IO.Path]::GetFileNameWithoutExtension($Pdf)
Write-Host "`nJSON    : output\$name.blocks.json" -ForegroundColor Green
Write-Host "Images  : output\preview\$($name)_p*.png" -ForegroundColor Green
Start-Process explorer.exe (Resolve-Path "output\preview")
