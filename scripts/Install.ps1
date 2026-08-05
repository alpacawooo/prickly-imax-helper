$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$AppVersion = "0.1.0"
$UvVersion = "0.11.15"
$ManagedPythonVersion = "3.12.12"
$TaskName = "Prickly IMAX Helper"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoDir = Split-Path -Parent $ScriptDir
if (-not $env:USERPROFILE -or -not $env:LOCALAPPDATA) {
    throw "Windows 사용자 프로필 경로를 확인할 수 없습니다."
}
$UserRoot = [IO.Path]::GetFullPath($env:USERPROFILE).TrimEnd('\')
$DefaultHome = Join-Path $env:LOCALAPPDATA "PricklyIMAXHelper"
$AppHome = if ($env:PRICKLY_IMAX_HOME) { [IO.Path]::GetFullPath($env:PRICKLY_IMAX_HOME) } else { $DefaultHome }
$ExpectedPrefix = $UserRoot + [IO.Path]::DirectorySeparatorChar
if (-not $AppHome.StartsWith($ExpectedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "설치 경로는 현재 사용자 홈의 하위 폴더여야 합니다: $AppHome"
}

$ChromeCandidates = @()
foreach ($Base in @($env:PROGRAMFILES, ${env:PROGRAMFILES(X86)}, $env:LOCALAPPDATA)) {
    if ($Base) { $ChromeCandidates += Join-Path $Base "Google\Chrome\Application\chrome.exe" }
}
$ChromeCandidates = $ChromeCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }
if (-not $ChromeCandidates) {
    throw "Google Chrome을 먼저 설치해 주세요."
}

$AppDir = Join-Path $AppHome "app\$AppVersion"
$VenvDir = Join-Path $AppHome "venv"
$BinDir = Join-Path $AppHome "bin"
$DryRun = $env:PRICKLY_INSTALL_DRY_RUN -eq "1"
New-Item -ItemType Directory -Force -Path $AppHome, (Join-Path $AppHome "logs"), $AppDir, $BinDir | Out-Null

if (-not $DryRun) {
    $ExistingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($ExistingTask) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    }
}

$RuntimeTarget = Join-Path $AppDir "runtime"
if (Test-Path -LiteralPath $RuntimeTarget) { Remove-Item -Recurse -Force -LiteralPath $RuntimeTarget }
Copy-Item -Recurse -Force (Join-Path $RepoDir "runtime") $RuntimeTarget
Copy-Item -Force (Join-Path $RepoDir "pyproject.toml") (Join-Path $AppDir "pyproject.toml")
Copy-Item -Force (Join-Path $RepoDir "uv.lock") (Join-Path $AppDir "uv.lock")

$Architecture = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
switch ($Architecture) {
    "X64" {
        $UvTarget = "x86_64-pc-windows-msvc"
        $UvSha256 = "04b98d414a9000e25e5e0e7c9f53749e66b790cdaffc582829e6f58c544ee11c"
    }
    "Arm64" {
        $UvTarget = "aarch64-pc-windows-msvc"
        $UvSha256 = "9eac2d68f3a66326c3e1fc97ef28bd54f1d13136ec092c2f0a8173ae12aaaf1e"
    }
    default { throw "지원하지 않는 Windows 아키텍처입니다: $Architecture" }
}

$BootstrapDir = Join-Path $AppHome "bootstrap\uv-$UvVersion"
$UvArchive = Join-Path $BootstrapDir "uv-$UvTarget.zip"
$UvExtractDir = Join-Path $BootstrapDir "uv-$UvTarget"
$UvExe = Join-Path $UvExtractDir "uv.exe"
New-Item -ItemType Directory -Force -Path $BootstrapDir | Out-Null
if (-not (Test-Path -LiteralPath $UvExe -PathType Leaf)) {
    Write-Host "검증된 관리형 Python 실행기를 준비합니다."
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $UvUrl = "https://github.com/astral-sh/uv/releases/download/$UvVersion/uv-$UvTarget.zip"
    Invoke-WebRequest -UseBasicParsing -Uri $UvUrl -OutFile $UvArchive
    $ActualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $UvArchive).Hash.ToLowerInvariant()
    if ($ActualHash -ne $UvSha256) {
        throw "uv 체크섬이 일치하지 않습니다. 설치를 중단합니다."
    }
    if (Test-Path -LiteralPath $UvExtractDir) { Remove-Item -Recurse -Force -LiteralPath $UvExtractDir }
    Expand-Archive -LiteralPath $UvArchive -DestinationPath $UvExtractDir -Force
}

$env:UV_PYTHON_INSTALL_DIR = Join-Path $AppHome "python"
$env:UV_CACHE_DIR = Join-Path $AppHome "cache\uv"
$env:UV_PROJECT_ENVIRONMENT = $VenvDir
& $UvExe sync --project $AppDir --locked --no-dev --no-install-project --python $ManagedPythonVersion --managed-python --quiet
if ($LASTEXITCODE -ne 0) { throw "잠긴 Python 실행 환경 설치에 실패했습니다." }

$PythonExe = Join-Path $VenvDir "Scripts\python.exe"
$RuntimeDir = Join-Path $AppDir "runtime"
$LauncherPy = Join-Path $BinDir "launcher.py"
$LauncherCmd = Join-Path $BinDir "prickly-imax.cmd"
$RuntimeLiteral = $RuntimeDir | ConvertTo-Json -Compress
$LauncherSource = @"
import sys
sys.path.insert(0, $RuntimeLiteral)
from prickly_imax_helper.cli import main
raise SystemExit(main())
"@
Set-Content -LiteralPath $LauncherPy -Value $LauncherSource -Encoding UTF8
$LauncherCmdSource = '@echo off' + "`r`n" + '"%~dp0..\venv\Scripts\python.exe" "%~dp0launcher.py" %*' + "`r`n"
Set-Content -LiteralPath $LauncherCmd -Value $LauncherCmdSource -Encoding ASCII

if ($DryRun) {
    Write-Host "Dry-run: 설정 페이지와 예약 작업 시작을 생략합니다."
} elseif (-not (Test-Path -LiteralPath (Join-Path $AppHome "config.json"))) {
    Write-Host "설정 페이지를 엽니다. CGV 로그인과 자동 예매 조건을 직접 확인해 주세요."
    & $LauncherCmd --home $AppHome setup
    if ($LASTEXITCODE -ne 0) { throw "설정을 완료하지 못했습니다." }
} else {
    Write-Host "기존 로컬 설정과 CGV 로그인 프로필을 유지합니다."
}

if (-not $DryRun) {
    Write-Host "좌석과 결제를 누르지 않는 연결 검사를 실행합니다."
    & $LauncherCmd --home $AppHome dry-run
    if ($LASTEXITCODE -ne 0) { throw "무클릭 연결 검사에 실패해 상주 감시를 시작하지 않습니다." }

    $Action = New-ScheduledTaskAction -Execute $PythonExe -Argument "`"$LauncherPy`" --home `"$AppHome`" run"
    $CurrentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $Trigger = New-ScheduledTaskTrigger -AtLogOn -User $CurrentUser
    $Principal = New-ScheduledTaskPrincipal -UserId $CurrentUser -LogonType Interactive -RunLevel Limited
    $Settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Force | Out-Null
    Start-ScheduledTask -TaskName $TaskName
}

Write-Host "Prickly IMAX Helper $AppVersion 설치가 완료됐습니다."
Write-Host "상태 확인: `"$LauncherCmd`" status"
