<#
.SYNOPSIS
    Checkmk agent plugin: Windows services and the accounts they run under.
.DESCRIPTION
    Prints every service, unfiltered. The evaluation (which accounts count as
    service accounts, which are allowed) happens on the Checkmk server in the
    check plugin service_accounts, so the plugin needs no configuration.

    <<<service_accounts:sep(124)>>>
    computer|<computer name>|<machine SID>
    service|<name>|<display name>|<account>|<account SID>|<start mode>|<state>
    error|<message>

    Keep this file ASCII only: Windows PowerShell 5.1 reads scripts without a
    BOM in the ANSI code page.
#>

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$script:SidCache = @{}

function Format-Field {
    # Pipes and line breaks would break the section format.
    param($Value)
    if ($null -eq $Value) { return '' }
    return (([string]$Value) -replace '[|\r\n]+', ' ').Trim()
}

function Get-MachineSid {
    # The SID prefix shared by the local accounts of this computer. A domain
    # controller has no local accounts: the query would walk the directory and
    # return the domain SID, so the field stays empty there.
    try {
        $role = (Get-CimInstance -ClassName Win32_ComputerSystem -Property DomainRole).DomainRole
        if ($role -ge 4) { return '' }
        $account = Get-CimInstance -ClassName Win32_UserAccount -Filter 'LocalAccount=True' |
            Select-Object -First 1
        if ($account) {
            $sid = New-Object System.Security.Principal.SecurityIdentifier($account.SID)
            return $sid.AccountDomainSid.Value
        }
    } catch {
        # Leave the field empty: the check then falls back to the account name.
    }
    return ''
}

function Get-AccountSid {
    # Empty if the account cannot be translated (deleted, domain not reachable).
    param([string]$Account)
    if ([string]::IsNullOrEmpty($Account)) { return '' }
    $key = $Account.ToLowerInvariant()
    if ($script:SidCache.ContainsKey($key)) { return $script:SidCache[$key] }

    $sid = ''
    if ($key -eq 'localsystem' -or $key -eq '.\localsystem') {
        # Not an account name the LSA can translate.
        $sid = 'S-1-5-18'
    } else {
        $name = $Account
        if ($name.StartsWith('.\')) { $name = $env:COMPUTERNAME + $name.Substring(1) }
        try {
            $ntAccount = New-Object System.Security.Principal.NTAccount($name)
            $sid = $ntAccount.Translate([System.Security.Principal.SecurityIdentifier]).Value
        } catch {
            $sid = ''
        }
    }
    $script:SidCache[$key] = $sid
    return $sid
}

Write-Host '<<<service_accounts:sep(124)>>>'
Write-Host ('computer|{0}|{1}' -f (Format-Field $env:COMPUTERNAME), (Get-MachineSid))

try {
    $services = Get-CimInstance -ClassName Win32_Service `
        -Property Name, DisplayName, StartName, StartMode, State | Sort-Object -Property Name
    foreach ($service in $services) {
        $fields = @(
            'service',
            (Format-Field $service.Name),
            (Format-Field $service.DisplayName),
            (Format-Field $service.StartName),
            (Get-AccountSid (Format-Field $service.StartName)),
            (Format-Field $service.StartMode),
            (Format-Field $service.State)
        )
        Write-Host ($fields -join '|')
    }
} catch {
    Write-Host ('error|' + (Format-Field $_.Exception.Message))
}
