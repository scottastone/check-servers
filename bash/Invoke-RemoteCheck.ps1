<#
.SYNOPSIS
    Runs the check-servers.sh or check-docker.sh scripts on a remote Linux host.

.DESCRIPTION
    This PowerShell script simplifies running the server and Docker health check scripts
    from a Windows machine. It connects to a predefined remote host via SSH and executes
    the specified check, passing along any additional arguments.
    It assumes the 'check-servers' and 'check-docker' commands are in the remote user's PATH.

.PARAMETER CheckType
    (Required) Specifies which check to run. Must be either 'servers' or 'docker'.

.PARAMETER Arguments
    Any additional arguments or flags to pass to the remote script.
    For example: -q, --history garage, -r sonarr

.EXAMPLE
    PS C:\> .\Invoke-RemoteCheck.ps1 servers -q
    Runs 'check-servers -q' on the remote host.

.EXAMPLE
    PS C:\> .\Invoke-RemoteCheck.ps1 docker -r sonarr
    Runs 'check-docker -r sonarr' on the remote host.

.EXAMPLE
    PS C:\> .\Invoke-RemoteCheck.ps1 servers --history garage
    Runs 'check-servers --history garage' on the remote host.

.LINK
    https://github.com/your-repo/check-servers
#>
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('servers', 'docker', 'dns')]
    [string]$CheckType,

    [Parameter(Position = 1, ValueFromRemainingArguments = $true)]
    [string[]]$Arguments
)

# ==========================================
# CONFIGURATION
# ==========================================
# Set the remote host and user for the SSH connection.
# You can use the hostname from your check-servers.conf (e.g., 'gus')
# if it's defined in your local SSH config or DNS. Otherwise, use the IP.
$RemoteHost = "gus"
$RemoteUser = "scott"
# ==========================================

# Determine the command to run based on the CheckType parameter.
$RemoteCommand = switch ($CheckType) {
    'servers' { "check-servers" }
    'docker'  { "check-docker" }
    'dns'     { "check-dns" }
}

# Join any additional arguments into a single string.
$ArgumentString = $Arguments -join ' '

# Construct the full command to be executed on the remote host.
$FinalCommand = "$RemoteCommand $ArgumentString"

Write-Host "Executing on '$($RemoteUser)@$($RemoteHost)': $FinalCommand"

# Use ssh.exe to run the command. The -t flag is used to allocate a pseudo-terminal,
# which helps ensure that color codes from the remote script are rendered correctly.
ssh.exe -t "$($RemoteUser)@$($RemoteHost)" -- $FinalCommand