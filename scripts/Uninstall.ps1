$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$TaskName = "Prickly IMAX Helper"
if (-not $env:USERPROFILE -or -not $env:LOCALAPPDATA) {
    throw "Windows 사용자 프로필 경로를 확인할 수 없습니다."
}
$UserRoot = [IO.Path]::GetFullPath($env:USERPROFILE).TrimEnd('\')
$DefaultHome = Join-Path $env:LOCALAPPDATA "PricklyIMAXHelper"
$AppHome = if ($env:PRICKLY_IMAX_HOME) { [IO.Path]::GetFullPath($env:PRICKLY_IMAX_HOME) } else { $DefaultHome }
$ExpectedPrefix = $UserRoot + [IO.Path]::DirectorySeparatorChar
if (-not $AppHome.StartsWith($ExpectedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "삭제 경로는 현재 사용자 홈의 하위 폴더여야 합니다: $AppHome"
}

Write-Host "다음 항목을 제거합니다:"
Write-Host "- 감시 예약 작업: $TaskName"
Write-Host "- 설치된 실행 파일: $AppHome\app, $AppHome\venv, $AppHome\bin"
$Answer = Read-Host "설정·로그·CGV 로그인 프로필까지 모두 삭제할까요? [y/N]"

Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
if ($Answer -match '^(?i:y|yes)$') {
    if (-not $AppHome.Equals($DefaultHome, [StringComparison]::OrdinalIgnoreCase)) {
        throw "안전을 위해 기본 설치 경로가 아닌 전체 삭제는 자동 실행하지 않습니다: $AppHome"
    }
    Remove-Item -Recurse -Force -LiteralPath $AppHome
    Write-Host "설정, 로그, 전용 CGV 로그인 프로필을 모두 삭제했습니다. 복구할 수 없습니다."
} else {
    foreach ($Name in @("app", "venv", "bin")) {
        $Target = Join-Path $AppHome $Name
        if (Test-Path -LiteralPath $Target) { Remove-Item -Recurse -Force -LiteralPath $Target }
    }
    Write-Host "프로그램만 제거했습니다. 설정과 CGV 로그인 프로필은 $AppHome 에 보존했습니다."
}
