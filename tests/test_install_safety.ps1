$ErrorActionPreference = "Stop"
$TempRoot = Join-Path $env:LOCALAPPDATA ("prickly-install-safety-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $TempRoot | Out-Null
try {
    $env:PRICKLY_IMAX_HOME = Join-Path $TempRoot "home"
    $env:PRICKLY_INSTALL_SAFETY_LIBRARY = "1"
    . (Join-Path $PSScriptRoot "..\scripts\Install.ps1")
    $PartialRuntime = Join-Path $AppHome "app\0.2.4\runtime"
    New-Item -ItemType Directory -Force -Path $PartialRuntime | Out-Null
    Set-Content -LiteralPath (Join-Path $PartialRuntime "stale-sentinel.txt") -Value "must disappear"
    Set-Content -LiteralPath (Join-Path $AppHome "config.json") -Value "preserve config"
    $ProfileMarker = Join-Path $AppHome "browser-profile\profile-marker"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ProfileMarker) | Out-Null
    Set-Content -LiteralPath $ProfileMarker -Value "preserve profile"
    $FakeUvMarker = Join-Path $TempRoot "fake-uv-ran"
    $FakeUv = Join-Path $TempRoot "uv.cmd"
    $TestPython = (Get-Command python -ErrorAction Stop).Source
    Set-Content -LiteralPath $FakeUv -Encoding ASCII -Value @(
        "@echo off",
        "echo ran>`"$FakeUvMarker`"",
        "`"$TestPython`" -m venv `"%UV_PROJECT_ENVIRONMENT%`""
    )
    $script:FakeUv = $FakeUv
    $OriginalUvInitializer = ${function:Initialize-PinnedUv}
    function Initialize-PinnedUv { return $script:FakeUv }
    New-Item -ItemType Directory -Force -Path (Join-Path $AppHome "state") | Out-Null

    $OriginalOwnerWriter = ${function:Write-InstallerLockOwner}
    function Write-InstallerLockOwner { throw "injected owner write failure" }
    $Rejected = $false
    try { Enter-InstallerLock } catch { $Rejected = $true }
    Set-Item -Path Function:Write-InstallerLockOwner -Value $OriginalOwnerWriter
    if (-not $Rejected -or (Test-Path -LiteralPath $InstallerLockDir) -or $null -ne $InstallerGateStream) { throw "owner write failure published or retained installer lock state" }
    Enter-InstallerLock
    Exit-InstallerLock

    $CrashScript = Join-Path $TempRoot "publish-before-token-exit.ps1"
    $InstallerSourcePath = (Resolve-Path (Join-Path $PSScriptRoot "..\scripts\Install.ps1")).Path.Replace("'", "''")
    $EscapedAppHome = $AppHome.Replace("'", "''")
    Set-Content -LiteralPath $CrashScript -Encoding UTF8 -Value @(
        '$ErrorActionPreference = "Stop"',
        "`$env:PRICKLY_IMAX_HOME = '$EscapedAppHome'",
        '$env:PRICKLY_INSTALL_SAFETY_LIBRARY = "1"',
        ". '$InstallerSourcePath'",
        'New-Item -ItemType Directory -Force -Path (Join-Path $AppHome "state") | Out-Null',
        'Enter-InstallerGate',
        '$CrashToken = [guid]::NewGuid().ToString("N")',
        'New-InstallerLockCandidate -CandidateToken $CrashToken',
        'Publish-InstallerLockCandidate',
        'exit 72'
    )
    $PowerShellExe = (Get-Process -Id $PID -ErrorAction Stop).Path
    & $PowerShellExe -NoProfile -ExecutionPolicy Bypass -File $CrashScript
    if ($LASTEXITCODE -ne 72 -or -not (Test-Path -LiteralPath $InstallerLockOwnerFile -PathType Leaf)) { throw "pre-token child did not leave a complete published lock" }
    Enter-InstallerLock
    Exit-InstallerLock

    $PartialCandidateToken = "cccccccccccc4ccc8ccccccccccccccc"
    $PartialCandidate = "$InstallerLockDir.candidate.$([int]::MaxValue).$PartialCandidateToken"
    New-Item -ItemType Directory -Path $PartialCandidate | Out-Null
    Set-Content -LiteralPath (Join-Path $PartialCandidate "owner") -Value "partial"
    Enter-InstallerLock
    if (Test-Path -LiteralPath $PartialCandidate) { throw "dead partial candidate was not recovered" }
    Exit-InstallerLock

    Enter-InstallerLock
    $FirstInstallerToken = $InstallerLockToken
    $script:InstallerLockToken = $null
    $Rejected = $false
    try {
        Enter-InstallerLock
        Sync-ManagedEnvironment
    } catch { $Rejected = $true }
    if (-not $Rejected -or (Test-Path -LiteralPath $FakeUvMarker) -or -not [string]::IsNullOrWhiteSpace($InstallerLockToken)) { throw "active installer lock allowed shared environment mutation" }
    $script:InstallerLockToken = $FirstInstallerToken
    Exit-InstallerLock

    New-Item -ItemType Directory -Path $InstallerLockDir | Out-Null
    Set-Content -LiteralPath $InstallerLockOwnerFile -Value @([int]::MaxValue, "dddddddddddd4ddd8ddddddddddddddd")
    $ReplacementToken = "eeeeeeeeeeee4eee8eeeeeeeeeeeeeee"
    $OriginalInstallerOwnerState = ${function:Get-InstallerOwnerState}
    $script:ReclaimQueryCount = 0
    function Get-InstallerOwnerState {
        $script:ReclaimQueryCount++
        if ($script:ReclaimQueryCount -eq 1) {
            Set-Content -LiteralPath $InstallerLockOwnerFile -Value @($PID, $ReplacementToken)
            return "Dead"
        }
        return "Live"
    }
    $Rejected = $false
    try { Enter-InstallerLock } catch { $Rejected = $true }
    Set-Item -Path Function:Get-InstallerOwnerState -Value $OriginalInstallerOwnerState
    $RestoredOwner = Read-InstallerLockOwner
    if (-not $Rejected -or $RestoredOwner.Pid -ne $PID -or $RestoredOwner.Token -ne $ReplacementToken -or $null -ne $InstallerGateStream) { throw "changed live owner was not restored after stale classification" }
    Remove-Item -Recurse -Force -LiteralPath $InstallerLockDir

    New-Item -ItemType Directory -Path $InstallerLockDir | Out-Null
    Set-Content -LiteralPath $InstallerLockOwnerFile -Value @([int]::MaxValue, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    Enter-InstallerLock
    if ([string]::IsNullOrWhiteSpace($InstallerLockToken)) { throw "dead installer owner was not adopted" }
    Exit-InstallerLock

    New-Item -ItemType Directory -Path $InstallerLockDir | Out-Null
    Set-Content -LiteralPath $InstallerLockOwnerFile -Value @([int]::MaxValue, "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    $OriginalInstallerOwnerState = ${function:Get-InstallerOwnerState}
    function Get-InstallerOwnerState { throw "ambiguous process query" }
    $Rejected = $false
    try { Enter-InstallerLock } catch { $Rejected = $true }
    Set-Item -Path Function:Get-InstallerOwnerState -Value $OriginalInstallerOwnerState
    if (-not $Rejected -or -not (Test-Path -LiteralPath $InstallerLockDir) -or (Test-Path -LiteralPath $FakeUvMarker)) { throw "ambiguous installer owner query did not fail closed" }
    Remove-Item -Recurse -Force -LiteralPath $InstallerLockDir

    $script:FakeTaskState = "Error"
    $OriginalTaskInspection = ${function:Get-ExistingTaskInspection}
    function Get-ExistingTaskInspection {
        if ($script:FakeTaskState -eq "Error") { throw "ambiguous task query" }
        if ($script:FakeTaskState -eq "Missing") { return @{ Found = $false; State = "Missing" } }
        return @{ Found = $true; State = $script:FakeTaskState }
    }
    $Rejected = $false
    try { Prepare-RuntimeReplacement } catch { $Rejected = $true }
    if (-not $Rejected -or (Test-Path -LiteralPath $FakeUvMarker) -or (Test-Path -LiteralPath (Join-Path $AppHome "state\update-in-progress")) -or -not (Test-Path -LiteralPath (Join-Path $PartialRuntime "stale-sentinel.txt"))) { throw "ambiguous service query did not fail before bootstrap" }
    $script:FakeTaskState = "Ready"
    $Rejected = $false
    try { Prepare-RuntimeReplacement } catch { $Rejected = $true }
    if (-not $Rejected -or (Test-Path -LiteralPath $FakeUvMarker) -or (Test-Path -LiteralPath (Join-Path $AppHome "state\update-in-progress")) -or -not (Test-Path -LiteralPath (Join-Path $PartialRuntime "stale-sentinel.txt"))) { throw "present service did not fail before bootstrap" }
    $script:FakeTaskState = "Missing"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ExistingLauncherCmd) | Out-Null
    Set-Content -LiteralPath $ExistingLauncherCmd -Value "old launcher"
    $Rejected = $false
    try { Prepare-RuntimeReplacement } catch { $Rejected = $true }
    if (-not $Rejected -or (Test-Path -LiteralPath $FakeUvMarker)) { throw "existing launcher without managed Python mutated the shared environment" }
    Remove-Item -LiteralPath $ExistingLauncherCmd -Force
    Prepare-RuntimeReplacement
    Set-Item -Path Function:Initialize-PinnedUv -Value $OriginalUvInitializer
    Set-Item -Path Function:Get-ExistingTaskInspection -Value $OriginalTaskInspection
    if (-not (Test-Path -LiteralPath $FakeUvMarker) -or -not (Test-Path -LiteralPath (Join-Path $VenvDir "Scripts\python.exe") -PathType Leaf)) { throw "partial install did not bootstrap the managed environment" }
    if ([string]::IsNullOrWhiteSpace($MaintenanceToken) -or -not (Test-Path -LiteralPath (Join-Path $AppHome "state\update-in-progress") -PathType Leaf)) { throw "partial install did not establish the update barrier" }
    if (Test-Path -LiteralPath (Join-Path $PartialRuntime "stale-sentinel.txt")) { throw "partial install retained stale runtime content" }
    if (Test-Path -LiteralPath (Join-Path $PartialRuntime "runtime")) { throw "partial install nested the release runtime" }
    if (-not (Test-Path -LiteralPath (Join-Path $PartialRuntime "prickly_imax_helper\__init__.py") -PathType Leaf)) { throw "partial install did not place the release package at the target depth" }
    if ((Get-Content -LiteralPath (Join-Path $AppHome "config.json") -Raw).Trim() -ne "preserve config" -or (Get-Content -LiteralPath $ProfileMarker -Raw).Trim() -ne "preserve profile") { throw "partial recovery changed user data" }
    Invoke-UpdateMaintenance -MaintenanceArguments @("end", "--token", $MaintenanceToken) | Out-Null
    $MaintenanceToken = $null
    $ValidStatus = ConvertFrom-StrictOldCliJson -Output @('{"status":"armed"}')
    if ($ValidStatus["status"] -ne "armed") { throw "valid status payload was not accepted" }
    $ValidStop = ConvertFrom-StrictOldCliJson -Output @('{"ok":true,"status":"stopped"}') -StopPayload
    if ($ValidStop["status"] -ne "stopped") { throw "valid stop payload was not accepted" }
    $Cases = @("not-json", "{}", '{status:''armed''}', '{''status'':''armed''}', '{"status":"submitting","status":"armed"}', '{"stat\u0075s":"submitting","status":"armed"}', '[{"status":"armed"}]', '{"status":"armed"}{"status":"armed"}', '{"status":"armed"} trailing', '{"status":"future"}', '{"status":"submitting"}')
    foreach ($Case in $Cases) {
        $Rejected = $false
        try { ConvertFrom-StrictOldCliJson -Output @($Case) | Out-Null } catch { $Rejected = $true }
        if (-not $Rejected) { throw "accepted unsafe status: $Case" }
    }
    foreach ($Case in @("not-json", '{"ok":true,"ok":false,"status":"stopped"}', '{"ok":true,"status":"unknown_after_submit","status":"stopped"}', '[{"ok":true,"status":"stopped"}]', '{"ok":false,"status":"stopped"}', '{"ok":true,"status":"unknown_after_submit"}', '{"ok":true,"status":"stopped","extra":1}')) {
        $Rejected = $false
        try { ConvertFrom-StrictOldCliJson -Output @($Case) -StopPayload | Out-Null } catch { $Rejected = $true }
        if (-not $Rejected) { throw "accepted unsafe stop: $Case" }
    }

    $FakeCli = Join-Path $TempRoot "old-cli.cmd"
    Set-Content -LiteralPath $FakeCli -Encoding ASCII -Value ('@echo off' + "`r`n" + 'if "%3"=="status" (echo {"status":"armed"}) else (echo {"ok":true,"status":"stopped"})')
    $script:QueryCount = 0
    $script:StopCount = 0
    $script:TaskStates = [System.Collections.Generic.Queue[string]]::new()
    @("Ready", "Ready") | ForEach-Object { $script:TaskStates.Enqueue($_) }
    function Global:Get-ScheduledTask { param([string]$TaskName) $script:QueryCount++; [pscustomobject]@{ State = $script:TaskStates.Dequeue() } }
    function Global:Stop-ScheduledTask { param([string]$TaskName) $script:StopCount++ }
    Stop-ExistingMonitorSafely -OldCli $FakeCli
    if ($script:QueryCount -ne 2 -or $script:StopCount -ne 1) { throw "valid lifecycle did not reach fresh scheduler inspection and teardown" }

    $script:TaskStates = [System.Collections.Generic.Queue[string]]::new()
    @("Ready", "Running") | ForEach-Object { $script:TaskStates.Enqueue($_) }
    $Rejected = $false
    try { Stop-ExistingMonitorSafely -OldCli $FakeCli } catch { $Rejected = $true }
    if (-not $Rejected) { throw "accepted stale Ready-to-Running task" }

    $script:TaskStates = [System.Collections.Generic.Queue[string]]::new()
    @("Ready", "Queued") | ForEach-Object { $script:TaskStates.Enqueue($_) }
    $Rejected = $false
    try { Stop-ExistingMonitorSafely -OldCli $FakeCli } catch { $Rejected = $true }
    if (-not $Rejected) { throw "accepted final queued task state" }

    function Global:Get-ScheduledTask { throw "query failed" }
    $Rejected = $false
    try { Stop-ExistingMonitorSafely -OldCli $FakeCli } catch { $Rejected = $true }
    if (-not $Rejected) { throw "accepted task query failure" }

    $env:PRICKLY_EXIT_TIMEOUT_SECONDS = "0"
    function Global:Get-ScheduledTask { [pscustomobject]@{ State = "Running" } }
    function Global:Start-Sleep { param([int]$Milliseconds) }
    $Rejected = $false
    $TimeoutMessage = ""
    try { Stop-ExistingMonitorSafely -OldCli $FakeCli } catch { $Rejected = $true; $TimeoutMessage = $_.Exception.Message }
    if (-not $Rejected) { throw "accepted resident timeout" }
    $TimeoutNumbers = @([regex]::Matches($TimeoutMessage, "[0-9]+") | ForEach-Object { $_.Value })
    if ($TimeoutNumbers.Count -ne 1 -or $TimeoutNumbers[0] -ne "0") {
        throw "timeout diagnostic did not report the effective timeout: $TimeoutMessage"
    }
    Write-Host "Windows installer safety behavior tests passed"
} finally {
    Remove-Item -Recurse -Force -LiteralPath $TempRoot -ErrorAction SilentlyContinue
    Remove-Item Env:PRICKLY_IMAX_HOME -ErrorAction SilentlyContinue
    Remove-Item Env:PRICKLY_INSTALL_SAFETY_LIBRARY -ErrorAction SilentlyContinue
    Remove-Item Env:PRICKLY_EXIT_TIMEOUT_SECONDS -ErrorAction SilentlyContinue
}
