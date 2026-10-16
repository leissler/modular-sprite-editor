# Build the SNES demo ROM on Windows with PVSnesLib's Windows tools, without make or MSYS2: the steps PVSnesLib's
# snes_rules (4.6) takes for this project, in the same order (hdr.asm from the Makefile's settings, every C file through
# 816-tcc, 816-opt and wla-65816, every assembly file through wla-65816, wlalink with PVSnesLib's libraries).
# PVSNESLIB_HOME may point at PVSnesLib (a Windows path); otherwise third_party\pvsneslib is used (the Windows kit has
# it there). LoROM only, like the demo.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File build_windows.ps1
#
# The ROM is not byte for byte the one make builds on Linux or macOS: wlalink orders sections of the same size the way
# the system's C library sorts them. tools/compare_snes_roms.py (in the source code) plays both and checks they draw
# the same. Paths are given relative to this folder, so it may lie in a folder whose name has spaces.

# Errors are checked by hand: with "Stop", Windows PowerShell 5.1 ends the script at the first warning a tool writes to
# stderr when its output is redirected (as on CI).
$ErrorActionPreference = "Continue"
Set-Location -LiteralPath $PSScriptRoot
$Utf8 = New-Object System.Text.UTF8Encoding($false)

function Fail([string]$message) {
    Write-Host ""
    Write-Host $message
    exit 1
}

function Run([string]$tool, [string[]]$arguments) {
    $global:LASTEXITCODE = 0
    & $tool @arguments 2>&1 | ForEach-Object { Write-Host "$_" }
    if ($LASTEXITCODE -ne 0) { Fail "$([IO.Path]::GetFileName($tool)) failed (exit code $LASTEXITCODE), see above." }
}

# A path inside this folder as relative to it (what snes_rules hands the tools are relative names and PVSnesLib's).
function Relative([string]$path) {
    $root = $PSScriptRoot.TrimEnd('\') + '\'
    if ($path.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) { return $path.Substring($root.Length) }
    return $path
}

function Write-Unix([string]$path, [string[]]$lines) {
    [IO.File]::WriteAllText((Join-Path $PSScriptRoot $path), (($lines -join "`n") + "`n"), $Utf8)
}

# The Makefile's settings (and the ROM size the exporter writes into modsprite_rom.mk): NAME := value lines.
$settings = @{}
$cflags = @()
foreach ($file in @("Makefile", "modsprite_rom.mk")) {
    if (-not (Test-Path -LiteralPath $file)) { continue }
    foreach ($line in [IO.File]::ReadAllLines((Join-Path $PSScriptRoot $file))) {
        if ($line -match '^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*:?=\s*(.*?)\s*$') { $settings[$Matches[1]] = $Matches[2] }
        elseif ($line -match '^\s*CFLAGS\s*\+=\s*(.*?)\s*$') { $cflags += $Matches[1] -split '\s+' }
    }
}
function Setting([string]$name, [string]$default) {
    if ($settings.ContainsKey($name) -and $settings[$name] -ne "") { return $settings[$name] }
    return $default
}
if ((Setting "HIROM" "") -eq "1") { Fail "HiROM is not supported here: build with PVSnesLib's make (MSYS2) instead." }
$romName = Setting "ROMNAME" ""
if ($romName -eq "") { Fail "The Makefile sets no ROMNAME." }
$fast = (Setting "FASTROM" "") -eq "1"
$src = Setting "SRC" "src"

$pvsneslib = $env:PVSNESLIB_HOME
if (-not $pvsneslib) { $pvsneslib = Join-Path $PSScriptRoot "third_party\pvsneslib" }
$tcc = Join-Path $pvsneslib "devkitsnes\bin\816-tcc.exe"
if (-not (Test-Path -LiteralPath $tcc)) {
    Fail "PVSnesLib not found: set PVSNESLIB_HOME or put PVSnesLib's Windows release into $PSScriptRoot\third_party\pvsneslib"
}
$assembler = Join-Path $pvsneslib "devkitsnes\bin\wla-65816.exe"
$linker = Join-Path $pvsneslib "devkitsnes\bin\wlalink.exe"
$optimiser = Join-Path $pvsneslib "devkitsnes\tools\816-opt.exe"
$pvs = (Relative $pvsneslib) -replace '\\', '/'
$speed = $(if ($fast) { "FastROM" } else { "SlowROM" })
$libraries = Relative (Join-Path $pvsneslib "pvsneslib\lib\LoROM_$speed")
if (-not (Test-Path -LiteralPath $libraries)) { Fail "PVSnesLib's libraries are missing: $libraries" }
Write-Host "LoROM $speed compilation is enabled"

# hdr.asm, as snes_rules fills in PVSnesLib's template.
$header = [IO.File]::ReadAllText((Join-Path $pvsneslib "devkitsnes\include\hdr.asm.in"))
$values = [ordered]@{
    "@HIROMDEF@" = ""
    "@FASTROMDEF@" = $(if ($fast) { ".DEFINE FASTROM 1" } else { "" })
    "@ROMTITLE@" = (Setting "ROMTITLE" $romName)
    "@CARTRIDGETYPE@" = (Setting "CARTRIDGETYPE" "00")
    "@ROMSIZE@" = (Setting "ROMSIZE" "08")
    "@SRAMSIZE@" = (Setting "SRAMSIZE" "00")
    "@COUNTRY@" = (Setting "COUNTRY" "01")
    "@LICENSEECODE@" = (Setting "LICENSEECODE" "00")
    "@VERSION@" = (Setting "VERSION" "00")
    "@ROMBANKS@" = (Setting "ROMBANKS" "8")
    "@ROMBANKSIZE@" = "8000"
    "@ROMMODE@" = "LOROM"
    "@ROMSPEED@" = $(if ($fast) { "FASTROM" } else { "SLOWROM" })
}
foreach ($key in $values.Keys) { $header = $header.Replace($key, $values[$key]) }
[IO.File]::WriteAllText((Join-Path $PSScriptRoot "hdr.asm"), $header, $Utf8)

# The sources make's $(wildcard) finds: this folder, then SRC three levels deep, each level in name order.
function Find-Sources([string]$extension) {
    $found = @()
    foreach ($glob in @("*$extension", "$src/*$extension", "$src/*/*$extension", "$src/*/*/*$extension")) {
        $names = @(Resolve-Path -Path $glob -Relative -ErrorAction SilentlyContinue |
                   ForEach-Object { ($_ -replace '^\.[\\/]', '') -replace '\\', '/' })
        [Array]::Sort($names, [StringComparer]::Ordinal)
        $found += $names
    }
    return $found
}
$cFiles = @(Find-Sources ".c")
$generated = @($cFiles | ForEach-Object { $_ -replace '\.c$', '.asm' })
# hdr.asm is included by the sources, not assembled on its own (a first make, which has not made it yet, does the same).
$asmFiles = @(Find-Sources ".asm" | Where-Object { $_ -ne "hdr.asm" -and $generated -notcontains $_ })

$includes = @($cflags | Where-Object { $_ } | ForEach-Object { $_.Replace('$(CURDIR)', '.') })
$includes += @("-I$pvs/pvsneslib/include", "-I$pvs/devkitsnes/include", "-I.")
$objects = @()
foreach ($c in $cFiles) {
    $base = $c -replace '\.c$', ''
    Write-Host "Compiling ... $([IO.Path]::GetFileName($c))"
    $compile = $includes + @("-Wall", "-c", $c)
    if ($fast) { $compile += "-F" }
    Run $tcc ($compile + @("-o", "$base.ps"))
    Run $optimiser @("-i", "$base.ps", "-o", "$base.asm")
    Run $assembler @("-d", "-s", "-x", "-o", "$base.obj", "$base.asm")
    $objects += "$base.obj"
}
foreach ($asm in $asmFiles) {
    Write-Host "Assembling ... $([IO.Path]::GetFileName($asm))"
    $base = $asm -replace '\.asm$', ''
    Run $assembler @("-d", "-s", "-x", "-o", "$base.obj", $asm)
    $objects += "$base.obj"
}

# The linkfile: the objects, then PVSnesLib's libraries (Windows paths, as snes_rules writes them on Windows).
$libraryFiles = @(Get-ChildItem -LiteralPath $libraries -Filter "*.obj" -File | ForEach-Object { $_.Name })
[Array]::Sort($libraryFiles, [StringComparer]::Ordinal)
Write-Unix "linkfile" (@("[objects]") + $objects + @($libraryFiles | ForEach-Object { Join-Path $libraries $_ }))
Write-Host "Linking ... $romName.sfc"
Remove-Item -LiteralPath "$romName.sym" -ErrorAction SilentlyContinue
Run $linker @("-d", "-s", "-v", "-A", "-c", "-L", $libraries, "linkfile", "$romName.sfc")

# The symbols for debuggers, as snes_rules leaves them: .symfull without the colons, .sym without section labels.
if (Test-Path -LiteralPath "$romName.sym") {
    $symbols = @([IO.File]::ReadAllLines((Join-Path $PSScriptRoot "$romName.sym")) |
                 ForEach-Object { $at = $_.IndexOf(':'); if ($at -ge 0) { $_.Remove($at, 1) } else { $_ } })
    Write-Unix "$romName.symfull" $symbols
    Write-Unix "$romName.sym" @($symbols | Where-Object { $_ -notmatch ' SECTIONSTART_| SECTIONEND_| RAM_USAGE_SLOT_' })
}

# make deletes what it made on the way; a compiled C file's .asm left here would be assembled twice by the next make.
foreach ($c in $cFiles) {
    $base = $c -replace '\.c$', ''
    Remove-Item -LiteralPath "$base.ps", "$base.asm" -ErrorAction SilentlyContinue
}
Remove-Item -LiteralPath $objects -ErrorAction SilentlyContinue

$rom = Get-Item -LiteralPath "$romName.sfc"
Write-Host ""
Write-Host "Build finished: $($rom.FullName) ($([int]($rom.Length / 1024)) KB)"
exit 0
