# ====================================================================
#  Weekly Schedule Widget - one-line installer
#
#    irm https://raw.githubusercontent.com/Giheon-Jeon/Schedule-Management/main/install.ps1 | iex
#
#  - Checks Python (with tkinter) and Git; offers to install them via winget
#  - Downloads the app to %LOCALAPPDATA%\ScheduleWidget
#    (change with:  $env:SCHEDULE_WIDGET_DIR = 'D:\Apps\ScheduleWidget'  before running)
#  - Registers autostart and launches the widget (setup.bat)
#  Running it again updates an existing install.
# ====================================================================

$Repo = 'https://github.com/Giheon-Jeon/Schedule-Management.git'
$Dir = if ($env:SCHEDULE_WIDGET_DIR) { $env:SCHEDULE_WIDGET_DIR } else { Join-Path $env:LOCALAPPDATA 'ScheduleWidget' }

function Write-Step([string]$n, [string]$msg) { Write-Host "[$n/4] $msg" -ForegroundColor Cyan }

function Update-SessionPath {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')
}

function Get-PythonVersion {
    # the Microsoft Store "python" stub exists even when Python is not installed,
    # so actually run it (and import tkinter) instead of just looking it up
    try {
        $v = & python -c "import sys, tkinter; print(sys.version.split()[0])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $v) { return "$v".Trim() }
    } catch { }
    return $null
}

function Test-Git {
    try { $null = & git --version 2>$null; return ($LASTEXITCODE -eq 0) } catch { return $false }
}

function Install-WithWinget([string]$name, [string[]]$wingetArgs) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "$name is required. Please install it manually, then run this installer again."
    }
    $answer = Read-Host "$name is not installed. Install it now with winget? (Y/n)"
    if ($answer -and $answer -notmatch '^[Yy]') { throw "$name is required." }
    & winget @wingetArgs
    Update-SessionPath
}

try {
    Write-Host ''
    Write-Host '  Weekly Schedule Widget - installer' -ForegroundColor White
    Write-Host "  -> $Dir" -ForegroundColor DarkGray
    Write-Host ''

    Write-Step 1 'Checking Python...'
    $py = Get-PythonVersion
    if (-not $py) {
        Install-WithWinget 'Python' @('install', '--id', 'Python.Python.3.13', '-e', '--source', 'winget',
            '--accept-package-agreements', '--accept-source-agreements',
            '--override', '/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_tcltk=1')
        $py = Get-PythonVersion
        if (-not $py) { throw 'Python was installed but is not usable yet. Open a new PowerShell window and run the installer again.' }
    }
    Write-Host "      Python $py" -ForegroundColor DarkGray

    Write-Step 2 'Checking Git...'
    if (-not (Test-Git)) {
        Install-WithWinget 'Git' @('install', '--id', 'Git.Git', '-e', '--source', 'winget',
            '--accept-package-agreements', '--accept-source-agreements')
        if (-not (Test-Git)) { throw 'Git was installed but is not usable yet. Open a new PowerShell window and run the installer again.' }
    }
    Write-Host "      $(& git --version)" -ForegroundColor DarkGray

    Write-Step 3 'Downloading the widget...'
    if (Test-Path (Join-Path $Dir '.git')) {
        & git -C $Dir pull --ff-only -q
        if ($LASTEXITCODE -ne 0) { throw "Could not update the existing install at $Dir" }
        Write-Host '      Updated existing install' -ForegroundColor DarkGray
    } else {
        if ((Test-Path $Dir) -and (Get-ChildItem -Force $Dir | Select-Object -First 1)) {
            throw "$Dir already exists and is not empty. Remove it or set `$env:SCHEDULE_WIDGET_DIR to another folder."
        }
        & git clone -q $Repo $Dir
        if ($LASTEXITCODE -ne 0) { throw 'Download failed. Check your internet connection.' }
    }

    Write-Step 4 'Registering autostart and launching...'
    & cmd.exe /c "`"$(Join-Path $Dir 'setup.bat')`""

    Write-Host ''
    Write-Host '  Installed! The widget is in the bottom-right corner (bring it up with Ctrl+Alt+W).' -ForegroundColor Green
    Write-Host ''
} catch {
    Write-Host ''
    Write-Host "  Install failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host ''
}
