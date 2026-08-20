$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$AppVersion = "0.2.4"
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
$RuntimeTarget = Join-Path $AppDir "runtime"
$VenvDir = Join-Path $AppHome "venv"
$BinDir = Join-Path $AppHome "bin"
$DryRun = $env:PRICKLY_INSTALL_DRY_RUN -eq "1"
$ExistingLauncherCmd = Join-Path $BinDir "prickly-imax.cmd"
$ExistingLauncherPy = Join-Path $BinDir "launcher.py"
$MaintenancePython = if ($env:PRICKLY_MAINTENANCE_PYTHON) { $env:PRICKLY_MAINTENANCE_PYTHON } else { Join-Path $VenvDir "Scripts\python.exe" }
$MaintenanceToken = $null
$InstallerLockDir = Join-Path $AppHome "state\installer.lock"
$InstallerLockOwnerFile = Join-Path $InstallerLockDir "owner"
$InstallerLockToken = $null
$InstallerGatePath = Join-Path $AppHome "state\installer.gate"
$InstallerGateStream = $null
$InstallerLockCandidateDir = $null
$InstallerLockCandidateToken = $null

function Read-InstallerLockOwner {
    param([string]$LockDir = $InstallerLockDir)
    $OwnerFile = Join-Path $LockDir "owner"
    if (-not (Test-Path -LiteralPath $OwnerFile -PathType Leaf)) {
        throw "기존 설치 잠금의 소유자 정보가 없어 안전하게 계속할 수 없습니다."
    }
    $Lines = @(Get-Content -LiteralPath $OwnerFile -ErrorAction Stop)
    $OwnerPid = 0
    if ($Lines.Count -ne 2 -or -not [int]::TryParse([string]$Lines[0], [ref]$OwnerPid) -or $OwnerPid -le 0 -or [string]$Lines[1] -notmatch '^[0-9A-Fa-f]{32}$') {
        throw "기존 설치 잠금의 소유자 정보가 잘못되어 안전하게 계속할 수 없습니다."
    }
    return @{ Pid = $OwnerPid; Token = [string]$Lines[1] }
}

function Enter-InstallerGate {
    if ($null -ne $InstallerGateStream) {
        throw "이 설치 프로세스가 이미 운영체제 잠금을 소유하고 있습니다."
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $AppHome "state") | Out-Null
    try {
        $script:InstallerGateStream = [IO.File]::Open(
            $InstallerGatePath,
            [IO.FileMode]::OpenOrCreate,
            [IO.FileAccess]::ReadWrite,
            [IO.FileShare]::None
        )
    } catch {
        $script:InstallerGateStream = $null
        throw "다른 설치 프로세스가 진행 중이거나 잠금 상태가 모호해 중단합니다: $($_.Exception.Message)"
    }
}

function Exit-InstallerGate {
    if ($null -eq $InstallerGateStream) { return }
    $GateStream = $InstallerGateStream
    $script:InstallerGateStream = $null
    $GateStream.Dispose()
}

function Restore-MovedInstallerLock {
    param([string]$MovedPath)
    if (Test-Path -LiteralPath $InstallerLockDir) {
        throw "변경된 설치 잠금을 원위치로 복원할 수 없어 중단합니다."
    }
    [IO.Directory]::Move($MovedPath, $InstallerLockDir)
}

function Write-InstallerLockOwner {
    param([string]$LockDir, [int]$OwnerPid, [string]$OwnerToken)
    Set-Content -LiteralPath (Join-Path $LockDir "owner") -Encoding ASCII -Value @($OwnerPid, $OwnerToken) -ErrorAction Stop
}

function Remove-CurrentInstallerLockCandidate {
    if ([string]::IsNullOrWhiteSpace($InstallerLockCandidateDir)) { return }
    $ExpectedDir = "$InstallerLockDir.candidate.$PID.$InstallerLockCandidateToken"
    if ($InstallerLockCandidateDir -ne $ExpectedDir) {
        throw "임시 설치 잠금 경로의 소유권을 확인할 수 없어 정리하지 않습니다."
    }
    $OwnerFile = Join-Path $InstallerLockCandidateDir "owner"
    Remove-Item -LiteralPath $OwnerFile -Force -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $InstallerLockCandidateDir) {
        Remove-Item -LiteralPath $InstallerLockCandidateDir -Force -ErrorAction Stop
    }
    $script:InstallerLockCandidateDir = $null
    $script:InstallerLockCandidateToken = $null
}

function New-InstallerLockCandidate {
    param([string]$CandidateToken)
    $script:InstallerLockCandidateToken = $CandidateToken
    $script:InstallerLockCandidateDir = "$InstallerLockDir.candidate.$PID.$CandidateToken"
    New-Item -ItemType Directory -Path $InstallerLockCandidateDir -ErrorAction Stop | Out-Null
    try {
        Write-InstallerLockOwner -LockDir $InstallerLockCandidateDir -OwnerPid $PID -OwnerToken $CandidateToken
        $CandidateOwner = Read-InstallerLockOwner -LockDir $InstallerLockCandidateDir
        if ($CandidateOwner.Pid -ne $PID -or $CandidateOwner.Token -ne $CandidateToken) {
            throw "임시 설치 잠금 소유자 정보가 예상과 달라 중단합니다."
        }
    } catch {
        Remove-CurrentInstallerLockCandidate
        throw
    }
}

function Publish-InstallerLockCandidate {
    if ($null -eq $InstallerGateStream -or [string]::IsNullOrWhiteSpace($InstallerLockCandidateDir)) {
        throw "임시 설치 잠금을 게시할 소유권이 없습니다."
    }
    if (Test-Path -LiteralPath $InstallerLockDir) {
        throw "기존 설치 잠금이 있어 임시 잠금을 게시하지 않습니다."
    }
    [IO.Directory]::Move($InstallerLockCandidateDir, $InstallerLockDir)
    $script:InstallerLockCandidateDir = $null
}

function Get-InstallerOwnerState {
    param([int]$OwnerPid)
    try {
        $Process = [System.Diagnostics.Process]::GetProcessById($OwnerPid)
    } catch {
        $Cause = $_.Exception
        while ($null -ne $Cause.InnerException) { $Cause = $Cause.InnerException }
        if ($Cause -is [System.ArgumentException]) { return "Dead" }
        throw "설치 잠금 소유자 프로세스를 안전하게 확인하지 못해 중단합니다: $($Cause.Message)"
    }
    try {
        if ($Process.HasExited) { return "Dead" }
        return "Live"
    } catch {
        throw "설치 잠금 소유자 프로세스를 안전하게 확인하지 못해 중단합니다: $($_.Exception.Message)"
    } finally {
        if ($null -ne $Process) {
            $Process.Dispose()
        }
    }
}

function Remove-AbandonedInstallerCandidates {
    $StateDir = Join-Path $AppHome "state"
    $Candidates = @(Get-ChildItem -LiteralPath $StateDir -Directory -Force -ErrorAction Stop | Where-Object { $_.Name -like "installer.lock.candidate.*" })
    if ($Candidates.Count -gt 32) {
        throw "중단된 임시 설치 잠금이 너무 많아 자동 복구를 중단합니다."
    }
    foreach ($Candidate in $Candidates) {
        if ($Candidate.Name -notmatch '^installer\.lock\.candidate\.([1-9][0-9]*)\.([0-9A-Fa-f]{32})$') {
            throw "중단된 임시 설치 잠금 경로가 모호해 자동으로 정리하지 않습니다."
        }
        $CandidatePid = [int]$Matches[1]
        $CandidateToken = [string]$Matches[2]
        if ((Get-InstallerOwnerState -OwnerPid $CandidatePid) -ne "Dead") {
            throw "임시 설치 잠금의 소유자가 live일 수 있어 정리하지 않습니다."
        }
        $Entries = @(Get-ChildItem -LiteralPath $Candidate.FullName -Force -ErrorAction Stop)
        if ($Entries.Count -gt 1 -or ($Entries.Count -eq 1 -and ($Entries[0].Name -ne "owner" -or $Entries[0].PSIsContainer))) {
            throw "중단된 임시 설치 잠금에 예상하지 못한 내용이 있어 정리하지 않습니다."
        }
        if ($Entries.Count -eq 1) {
            $Lines = @(Get-Content -LiteralPath $Entries[0].FullName -ErrorAction Stop)
            $RecordedPid = 0
            $RecordIsComplete = $Lines.Count -eq 2 -and [int]::TryParse([string]$Lines[0], [ref]$RecordedPid) -and $RecordedPid -gt 0 -and [string]$Lines[1] -match '^[0-9A-Fa-f]{32}$'
            if ($RecordIsComplete -and ($RecordedPid -ne $CandidatePid -or [string]$Lines[1] -ne $CandidateToken)) {
                throw "임시 설치 잠금의 경로와 소유자 정보가 달라 정리하지 않습니다."
            }
            Remove-Item -LiteralPath $Entries[0].FullName -Force -ErrorAction Stop
        }
        Remove-Item -LiteralPath $Candidate.FullName -Force -ErrorAction Stop
    }
}

function Enter-InstallerLock {
    if (-not [string]::IsNullOrWhiteSpace($InstallerLockToken)) {
        throw "이 설치 프로세스가 이미 잠금을 소유하고 있습니다."
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $AppHome "state") | Out-Null
    Enter-InstallerGate
    try {
        Remove-AbandonedInstallerCandidates
        $CandidateToken = [guid]::NewGuid().ToString("N")
        New-InstallerLockCandidate -CandidateToken $CandidateToken
        if (-not (Test-Path -LiteralPath $InstallerLockDir)) {
            Publish-InstallerLockCandidate
            $script:InstallerLockToken = $CandidateToken
            $script:InstallerLockCandidateToken = $null
            return
        }
        if (-not (Test-Path -LiteralPath $InstallerLockDir -PathType Container)) {
            throw "설치 잠금 경로가 모호해 안전하게 계속할 수 없습니다."
        }
        $ObservedOwner = Read-InstallerLockOwner
        if ((Get-InstallerOwnerState -OwnerPid $ObservedOwner.Pid) -ne "Dead") {
            throw "다른 설치 프로세스가 진행 중이라 중단합니다."
        }
        $StalePath = "$InstallerLockDir.stale.$CandidateToken"
        [IO.Directory]::Move($InstallerLockDir, $StalePath)
        try {
            $MovedOwner = Read-InstallerLockOwner -LockDir $StalePath
            if ($MovedOwner.Pid -ne $ObservedOwner.Pid -or $MovedOwner.Token -ne $ObservedOwner.Token) {
                throw "이동된 설치 잠금의 소유자가 최초 검증과 달라 중단합니다."
            }
            if ((Get-InstallerOwnerState -OwnerPid $MovedOwner.Pid) -ne "Dead") {
                throw "이동된 설치 잠금의 소유자가 더 이상 dead로 확인되지 않아 중단합니다."
            }
            $StaleEntries = @(Get-ChildItem -LiteralPath $StalePath -Force -ErrorAction Stop)
            if ($StaleEntries.Count -ne 1 -or $StaleEntries[0].Name -ne "owner" -or $StaleEntries[0].PSIsContainer) {
                throw "중단된 설치 잠금에 예상하지 못한 내용이 있어 중단합니다."
            }
        } catch {
            Restore-MovedInstallerLock -MovedPath $StalePath
            throw
        }
        Remove-Item -LiteralPath (Join-Path $StalePath "owner") -Force -ErrorAction Stop
        Remove-Item -LiteralPath $StalePath -Force -ErrorAction Stop
        Publish-InstallerLockCandidate
        $script:InstallerLockToken = $CandidateToken
        $script:InstallerLockCandidateToken = $null
    } catch {
        try {
            Remove-CurrentInstallerLockCandidate
        } finally {
            Exit-InstallerGate
        }
        throw
    }
}

function Exit-InstallerLock {
    try {
        if ([string]::IsNullOrWhiteSpace($InstallerLockToken)) {
            Remove-CurrentInstallerLockCandidate
            return
        }
        $Owner = Read-InstallerLockOwner
        if ($Owner.Pid -ne $PID -or $Owner.Token -ne $InstallerLockToken) {
            throw "설치 잠금 소유권이 달라 자동으로 해제하지 않습니다."
        }
        $ReleasedPath = "$InstallerLockDir.released.$InstallerLockToken"
        [IO.Directory]::Move($InstallerLockDir, $ReleasedPath)
        $script:InstallerLockToken = $null
        Remove-Item -LiteralPath (Join-Path $ReleasedPath "owner") -Force -ErrorAction Stop
        Remove-Item -LiteralPath $ReleasedPath -Force -ErrorAction Stop
    } finally {
        Exit-InstallerGate
    }
}

function Invoke-UpdateMaintenance {
    param([string[]]$MaintenanceArguments)
    $PreviousPythonPath = $env:PYTHONPATH
    try {
        $RuntimeSource = Join-Path $RepoDir "runtime"
        $env:PYTHONPATH = if ($PreviousPythonPath) { "$RuntimeSource$([IO.Path]::PathSeparator)$PreviousPythonPath" } else { $RuntimeSource }
        $Output = & $MaintenancePython -m prickly_imax_helper.maintenance --home $AppHome @MaintenanceArguments
        if ($LASTEXITCODE -ne 0) { throw "업데이트 유지보수 작업에 실패했습니다: $($MaintenanceArguments[0])" }
        return $Output
    } finally {
        if ($null -eq $PreviousPythonPath) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue } else { $env:PYTHONPATH = $PreviousPythonPath }
    }
}

function Start-UpdateMaintenance {
    if (-not (Test-Path -LiteralPath $MaintenancePython -PathType Leaf)) {
        throw "기존 관리형 Python을 찾을 수 없어 안전한 업데이트 장벽을 만들 수 없습니다."
    }
    $MaintenanceArguments = if (Test-Path -LiteralPath $ExistingLauncherCmd -PathType Leaf) {
        @("arm", "--launcher", $ExistingLauncherPy, "--runtime", (Join-Path $RepoDir "runtime"))
    } else {
        @("begin")
    }
    $script:MaintenanceToken = [string](Invoke-UpdateMaintenance -MaintenanceArguments $MaintenanceArguments)
    if ([string]::IsNullOrWhiteSpace($script:MaintenanceToken)) { throw "업데이트 장벽 소유권을 확인하지 못했습니다." }
}

function Test-ExistingInstallNeedsMaintenance {
    return (Test-Path -LiteralPath $ExistingLauncherCmd -PathType Leaf) -or (Test-Path -LiteralPath $RuntimeTarget -PathType Container)
}

function Skip-StrictJsonWhitespace {
    param([string]$Text, [ref]$Index)
    while ($Index.Value -lt $Text.Length -and ([string]$Text[$Index.Value]) -in @(" ", "`t", "`r", "`n")) { $Index.Value++ }
}

function Read-StrictJsonString {
    param([string]$Text, [ref]$Index)
    if ($Index.Value -ge $Text.Length -or $Text[$Index.Value] -ne '"') { throw "expected JSON string" }
    $Index.Value++
    $Builder = New-Object System.Text.StringBuilder
    while ($Index.Value -lt $Text.Length) {
        $Character = [string]$Text[$Index.Value]
        $Index.Value++
        if ($Character -eq '"') { return $Builder.ToString() }
        if ($Character -eq '\') {
            if ($Index.Value -ge $Text.Length) { throw "unterminated JSON escape" }
            $Escape = [string]$Text[$Index.Value]
            $Index.Value++
            switch ($Escape) {
                '"' { [void]$Builder.Append('"') }
                '\' { [void]$Builder.Append('\') }
                '/' { [void]$Builder.Append('/') }
                'b' { [void]$Builder.Append([char]8) }
                'f' { [void]$Builder.Append([char]12) }
                'n' { [void]$Builder.Append("`n") }
                'r' { [void]$Builder.Append("`r") }
                't' { [void]$Builder.Append("`t") }
                'u' {
                    if ($Index.Value + 4 -gt $Text.Length) { throw "short JSON unicode escape" }
                    $Hex = $Text.Substring($Index.Value, 4)
                    if ($Hex -notmatch '^[0-9a-fA-F]{4}$') { throw "invalid JSON unicode escape" }
                    [void]$Builder.Append([char][Convert]::ToInt32($Hex, 16))
                    $Index.Value += 4
                }
                default { throw "invalid JSON escape" }
            }
        } elseif ([int][char]$Character -lt 32) {
            throw "unescaped JSON control character"
        } else {
            [void]$Builder.Append($Character)
        }
    }
    throw "unterminated JSON string"
}

function Read-StrictJsonValue {
    param([string]$Text, [ref]$Index)
    Skip-StrictJsonWhitespace $Text $Index
    if ($Index.Value -ge $Text.Length) { throw "missing JSON value" }
    $Character = [string]$Text[$Index.Value]
    if ($Character -eq '"') { [void](Read-StrictJsonString $Text $Index); return }
    if ($Character -eq '{') { Read-StrictJsonObject $Text $Index; return }
    if ($Character -eq '[') {
        $Index.Value++
        Skip-StrictJsonWhitespace $Text $Index
        if ($Index.Value -lt $Text.Length -and $Text[$Index.Value] -eq ']') { $Index.Value++; return }
        while ($true) {
            Read-StrictJsonValue $Text $Index
            Skip-StrictJsonWhitespace $Text $Index
            if ($Index.Value -ge $Text.Length) { throw "unterminated JSON array" }
            if ($Text[$Index.Value] -eq ']') { $Index.Value++; return }
            if ($Text[$Index.Value] -ne ',') { throw "invalid JSON array separator" }
            $Index.Value++
        }
    }
    foreach ($Literal in @("true", "false", "null")) {
        if ($Text.Substring($Index.Value).StartsWith($Literal, [StringComparison]::Ordinal)) { $Index.Value += $Literal.Length; return }
    }
    $Number = [regex]::Match($Text.Substring($Index.Value), '^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?')
    if (-not $Number.Success) { throw "invalid JSON value" }
    $Index.Value += $Number.Length
}

function Read-StrictJsonObject {
    param([string]$Text, [ref]$Index)
    if ($Index.Value -ge $Text.Length -or $Text[$Index.Value] -ne '{') { throw "expected JSON object" }
    $Index.Value++
    $Keys = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
    Skip-StrictJsonWhitespace $Text $Index
    if ($Index.Value -lt $Text.Length -and $Text[$Index.Value] -eq '}') { $Index.Value++; return }
    while ($true) {
        Skip-StrictJsonWhitespace $Text $Index
        $Key = Read-StrictJsonString $Text $Index
        if (-not $Keys.Add($Key)) { throw "duplicate JSON member" }
        Skip-StrictJsonWhitespace $Text $Index
        if ($Index.Value -ge $Text.Length -or $Text[$Index.Value] -ne ':') { throw "missing JSON member separator" }
        $Index.Value++
        Read-StrictJsonValue $Text $Index
        Skip-StrictJsonWhitespace $Text $Index
        if ($Index.Value -ge $Text.Length) { throw "unterminated JSON object" }
        if ($Text[$Index.Value] -eq '}') { $Index.Value++; return }
        if ($Text[$Index.Value] -ne ',') { throw "invalid JSON object separator" }
        $Index.Value++
    }
}

function Test-StrictJsonObjectSyntax {
    param([string]$Text)
    $Index = 0
    Skip-StrictJsonWhitespace $Text ([ref]$Index)
    Read-StrictJsonObject $Text ([ref]$Index)
    Skip-StrictJsonWhitespace $Text ([ref]$Index)
    if ($Index -ne $Text.Length) { throw "trailing JSON content" }
}

function ConvertFrom-StrictOldCliJson {
    param([object[]]$Output, [switch]$StopPayload)
    $Text = [string]::Join([Environment]::NewLine, @($Output))
    if ([string]::IsNullOrWhiteSpace($Text)) { throw "기존 CLI 응답이 비어 있어 업데이트를 중단합니다." }
    try {
        Test-StrictJsonObjectSyntax $Text
        Add-Type -AssemblyName System.Web.Extensions -ErrorAction Stop
        $Payload = (New-Object System.Web.Script.Serialization.JavaScriptSerializer).DeserializeObject($Text)
    } catch { throw "기존 CLI 응답이 JSON 객체 하나가 아니어서 업데이트를 중단합니다." }
    if ($Payload -isnot [System.Collections.IDictionary]) { throw "기존 CLI 응답이 JSON 객체 하나가 아니어서 업데이트를 중단합니다." }
    $SafeStatus = @("unconfigured", "login_required", "armed", "staging", "completed", "recovering", "rate_limited", "blocked_duplicate", "blocked_payment", "fatal", "stopped")
    if ($Payload["status"] -isnot [string]) { throw "기존 CLI 상태가 없어 업데이트를 중단합니다." }
    if ($StopPayload) {
        if ($Payload.Count -ne 2 -or -not ($Payload.Keys -contains "ok") -or -not ($Payload.Keys -contains "status") -or $Payload["ok"] -isnot [bool] -or -not $Payload["ok"] -or $Payload["status"] -notin @("completed", "blocked_duplicate", "blocked_payment", "fatal", "stopped")) {
            throw "기존 CLI 중지 결과를 안전하게 증명하지 못해 업데이트를 중단합니다."
        }
    } elseif ($Payload["status"] -notin $SafeStatus) {
        throw "기존 CLI 상태를 안전하게 증명하지 못해 업데이트를 중단합니다."
    }
    return $Payload
}

function Get-ExistingTaskInspection {
    try {
        $Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
        return @{ Found = $true; State = [string]$Task.State }
    } catch {
        if ($_.FullyQualifiedErrorId -match "NoMatchingMSFT_ScheduledTask|TaskNotFound") { return @{ Found = $false; State = "Missing" } }
        throw "예약 작업 상태를 확인하지 못해 업데이트를 중단합니다: $($_.Exception.Message)"
    }
}

function Stop-ExistingMonitorSafely {
    param([string]$OldCli)
    if (Test-Path -LiteralPath $OldCli -PathType Leaf) {
        $OldStatusOutput = & $OldCli --home $AppHome status
        if ($LASTEXITCODE -ne 0) { throw "기존 설치 상태를 확인하지 못해 업데이트를 중단합니다." }
        $OldStatus = ConvertFrom-StrictOldCliJson -Output $OldStatusOutput
        $OldStopOutput = & $OldCli --home $AppHome stop
        if ($LASTEXITCODE -ne 0) { throw "기존 감시에 중지 요청을 전달하지 못해 업데이트를 중단합니다." }
        $OldStop = ConvertFrom-StrictOldCliJson -Output $OldStopOutput -StopPayload
        $ExitTimeoutSeconds = if ($env:PRICKLY_EXIT_TIMEOUT_SECONDS) { [int]$env:PRICKLY_EXIT_TIMEOUT_SECONDS } else { 60 }
        $ExitDeadline = [DateTime]::UtcNow.AddSeconds($ExitTimeoutSeconds)
        do {
            $Inspection = Get-ExistingTaskInspection
            if (-not $Inspection.Found) { break }
            if ($Inspection.State -eq "Running") {
                if ([DateTime]::UtcNow -ge $ExitDeadline) { throw "상주 감시가 ${ExitTimeoutSeconds}초 안에 종료되지 않아 업데이트를 중단합니다." }
                Start-Sleep -Milliseconds 250
                continue
            }
            if ($Inspection.State -notin @("Ready", "Disabled")) { throw "예약 작업 상태를 안전하게 증명하지 못해 업데이트를 중단합니다: $($Inspection.State)" }
            break
        } while ($true)
    } else {
        $Inspection = Get-ExistingTaskInspection
        if ($Inspection.Found) { throw "기존 감시 서비스의 CLI를 찾을 수 없어 상태를 안전하게 확인하지 못했습니다. 업데이트를 중단합니다." }
        return
    }
    if ($Inspection.Found) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction Stop
        $FinalInspection = Get-ExistingTaskInspection
        if ($FinalInspection.Found -and $FinalInspection.State -notin @("Ready", "Disabled")) { throw "예약 작업 중지 결과를 안전하게 증명하지 못해 업데이트를 중단합니다: $($FinalInspection.State)" }
    }
}

function Assert-ServiceAbsentForBootstrap {
    $Inspection = Get-ExistingTaskInspection
    if ($Inspection.Found) {
        throw "관리형 Python 준비 전에 기존 예약 작업이 없음을 증명하지 못했습니다. 업데이트를 중단합니다."
    }
}

function Initialize-PinnedUv {
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
    $UvExecutable = Join-Path $UvExtractDir "uv.exe"
    New-Item -ItemType Directory -Force -Path $BootstrapDir | Out-Null
    if (-not (Test-Path -LiteralPath $UvExecutable -PathType Leaf)) {
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
    return $UvExecutable
}

function Sync-ManagedEnvironment {
    $UvExecutable = [string](Initialize-PinnedUv)
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $AppHome "python"
    $env:UV_CACHE_DIR = Join-Path $AppHome "cache\uv"
    $env:UV_PROJECT_ENVIRONMENT = $VenvDir
    & $UvExecutable sync --project $RepoDir --locked --no-dev --no-install-project --python $ManagedPythonVersion --managed-python --quiet
    if ($LASTEXITCODE -ne 0) { throw "잠긴 Python 실행 환경 설치에 실패했습니다." }
}

function Prepare-RuntimeReplacement {
    $HasLauncher = Test-Path -LiteralPath $ExistingLauncherCmd -PathType Leaf
    $HasMaintenancePython = Test-Path -LiteralPath $MaintenancePython -PathType Leaf
    if ($HasLauncher -and -not $HasMaintenancePython) {
        throw "기존 실행기가 있지만 관리형 Python이 없어 활성 설치를 안전하게 갱신할 수 없습니다."
    }
    if ($HasMaintenancePython) {
        Start-UpdateMaintenance
        Stop-ExistingMonitorSafely -OldCli $ExistingLauncherCmd
        Sync-ManagedEnvironment
    } else {
        Assert-ServiceAbsentForBootstrap
        Sync-ManagedEnvironment
        Start-UpdateMaintenance
        Stop-ExistingMonitorSafely -OldCli $ExistingLauncherCmd
    }
    Invoke-UpdateMaintenance -MaintenanceArguments @(
        "replace-runtime", "--token", $MaintenanceToken, "--source", (Join-Path $RepoDir "runtime"), "--target", $RuntimeTarget
    ) | Out-Null
}

if ($env:PRICKLY_INSTALL_SAFETY_LIBRARY -eq "1") { return }

if ($DryRun -and ((Test-Path -LiteralPath (Join-Path $AppDir "runtime")) -or (Test-Path -LiteralPath $VenvDir))) {
    Write-Host "Dry-run: 기존 runtime/venv는 변경하지 않습니다."
    exit 0
}
try {
New-Item -ItemType Directory -Force -Path $AppHome, (Join-Path $AppHome "state") | Out-Null
Enter-InstallerLock
New-Item -ItemType Directory -Force -Path (Join-Path $AppHome "logs"), $AppDir, $BinDir | Out-Null
Prepare-RuntimeReplacement
Copy-Item -Force (Join-Path $RepoDir "pyproject.toml") (Join-Path $AppDir "pyproject.toml")
Copy-Item -Force (Join-Path $RepoDir "uv.lock") (Join-Path $AppDir "uv.lock")

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
    $StopRequest = Join-Path $AppHome "state\stop-requested"
    $StopRequestBackup = Join-Path $AppHome "state\stop-requested.install-backup"
    Remove-Item -LiteralPath $StopRequestBackup -Force -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $StopRequest) {
        Move-Item -LiteralPath $StopRequest -Destination $StopRequestBackup -Force
    }
    try {
        & $LauncherCmd --home $AppHome dry-run
        if ($LASTEXITCODE -ne 0) { throw "무클릭 연결 검사에 실패해 상주 감시를 시작하지 않습니다." }
    } catch {
        if (Test-Path -LiteralPath $StopRequestBackup) {
            Move-Item -LiteralPath $StopRequestBackup -Destination $StopRequest -Force
        }
        throw
    }
    Remove-Item -LiteralPath $StopRequestBackup -Force -ErrorAction SilentlyContinue

    $Action = New-ScheduledTaskAction -Execute $PythonExe -Argument "`"$LauncherPy`" --home `"$AppHome`" run"
    $CurrentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $Trigger = New-ScheduledTaskTrigger -AtLogOn -User $CurrentUser
    $Principal = New-ScheduledTaskPrincipal -UserId $CurrentUser -LogonType Interactive -RunLevel Limited
    $Settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Force | Out-Null
    if ($MaintenanceToken) {
        Invoke-UpdateMaintenance -MaintenanceArguments @("end", "--token", $MaintenanceToken) | Out-Null
        $MaintenanceToken = $null
    }
    Start-ScheduledTask -TaskName $TaskName
}

if ($DryRun -and $MaintenanceToken) {
    Invoke-UpdateMaintenance -MaintenanceArguments @("end", "--token", $MaintenanceToken) | Out-Null
    $MaintenanceToken = $null
}

Write-Host "Prickly IMAX Helper $AppVersion 설치가 완료됐습니다."
Write-Host "상태 확인: `"$LauncherCmd`" status"
} finally {
    Exit-InstallerLock
}
