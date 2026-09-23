<#
.SYNOPSIS
    Crea (o elimina) los accesos directos de Media Downloader en el Escritorio
    y en el Menu Inicio.

.DESCRIPTION
    Busca el ejecutable en este orden:
      1. -Target (ruta indicada por el usuario)
      2. dist\MediaDownloader\MediaDownloader.exe   (build --onedir)
      3. dist\MediaDownloader.exe                   (build --onefile)
      4. .venv\Scripts\pythonw.exe main.py          (modo codigo fuente, sin consola)

    Usa el objeto COM WScript.Shell, incluido en Windows: no requiere pywin32.

.EXAMPLE
    .\install_shortcuts_windows.ps1
    .\install_shortcuts_windows.ps1 -NoDesktop
    .\install_shortcuts_windows.ps1 -Target "D:\Apps\MediaDownloader\MediaDownloader.exe"
    .\install_shortcuts_windows.ps1 -Uninstall
#>
[CmdletBinding()]
param(
    [string]$Target,
    [switch]$NoDesktop,
    [switch]$NoStartMenu,
    [switch]$Uninstall,
    # Permiten redirigir las carpetas (pruebas o instalaciones personalizadas).
    [string]$DesktopDir = [Environment]::GetFolderPath('Desktop'),
    [string]$StartMenuDir = [Environment]::GetFolderPath('Programs')
)

$ErrorActionPreference = 'Stop'
$AppName = 'Media Downloader'
$Description = 'Descarga musica y videos de YouTube'
$ProjectRoot = Split-Path -Parent $PSScriptRoot

$locations = @()
if (-not $NoDesktop) { $locations += $DesktopDir }
if (-not $NoStartMenu) { $locations += $StartMenuDir }
if ($locations.Count -eq 0) { throw 'No hay destinos: se usaron -NoDesktop y -NoStartMenu a la vez.' }

if ($Uninstall) {
    foreach ($dir in $locations) {
        $lnk = Join-Path $dir "$AppName.lnk"
        if (Test-Path -LiteralPath $lnk) {
            Remove-Item -LiteralPath $lnk -Force
            Write-Host "Eliminado: $lnk"
        }
    }
    return
}

function Resolve-Launch {
    if ($Target) {
        if (-not (Test-Path -LiteralPath $Target -PathType Leaf)) { throw "No existe el ejecutable: $Target" }
        $exe = (Resolve-Path -LiteralPath $Target).Path
        return @{ Path = $exe; Args = ''; WorkDir = Split-Path -Parent $exe; Icon = "$exe,0" }
    }
    $candidates = @(
        (Join-Path $ProjectRoot 'dist\MediaDownloader\MediaDownloader.exe'),
        (Join-Path $ProjectRoot 'dist\MediaDownloader.exe')
    )
    foreach ($exe in $candidates) {
        if (Test-Path -LiteralPath $exe -PathType Leaf) {
            return @{ Path = $exe; Args = ''; WorkDir = Split-Path -Parent $exe; Icon = "$exe,0" }
        }
    }
    # Modo codigo fuente: pythonw.exe no abre ventana de consola.
    $pythonw = Join-Path $ProjectRoot '.venv\Scripts\pythonw.exe'
    if (Test-Path -LiteralPath $pythonw -PathType Leaf) {
        Write-Warning 'No se encontro el ejecutable compilado; el acceso directo usara .venv\Scripts\pythonw.exe main.py'
        return @{
            Path    = $pythonw
            Args    = '"' + (Join-Path $ProjectRoot 'main.py') + '"'
            WorkDir = $ProjectRoot
            Icon    = (Join-Path $ProjectRoot 'assets\icon.ico') + ',0'
        }
    }
    throw 'No se encontro la aplicacion. Compila con "python build.py" o crea el entorno .venv (ver README).'
}

$launch = Resolve-Launch
$shell = New-Object -ComObject WScript.Shell

foreach ($dir in $locations) {
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $lnkPath = Join-Path $dir "$AppName.lnk"
    $shortcut = $shell.CreateShortcut($lnkPath)
    $shortcut.TargetPath = $launch.Path
    $shortcut.Arguments = $launch.Args
    $shortcut.WorkingDirectory = $launch.WorkDir
    $shortcut.IconLocation = $launch.Icon
    $shortcut.Description = $Description
    $shortcut.WindowStyle = 1
    $shortcut.Save()
    Write-Host "Creado: $lnkPath"
}

Write-Host "Listo. Destino: $($launch.Path) $($launch.Args)"
