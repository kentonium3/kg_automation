# Deploy committed files from git repository to Dropbox
# PowerShell version for Windows

# Set paths
$RepoDir = "$env:USERPROFILE\Documents\Code\kg-automation"
$DropboxDir = "$env:USERPROFILE\Dropbox\Automation"

Write-Host "🚀 Deploying kg-automation to Dropbox..." -ForegroundColor Green

# Copy bootstrap file to top-level (critical for AI sessions)
Write-Host "🎯 Syncing Bootstrap to Top-Level..." -ForegroundColor Yellow
Copy-Item -Path "$RepoDir\ai-agents\ai-context-bootstrap.md" -Destination "$DropboxDir\ai-agents\ai-context-bootstrap.md" -Force

# Copy documentation
Write-Host "📚 Syncing Documentation..." -ForegroundColor Yellow
if (Test-Path "$DropboxDir\Documentation") {
    Remove-Item -Path "$DropboxDir\Documentation\*" -Recurse -Force
}
if (-not (Test-Path "$DropboxDir\Documentation")) {
    New-Item -ItemType Directory -Path "$DropboxDir\Documentation" -Force | Out-Null
}
Copy-Item -Path "$RepoDir\Documentation\*" -Destination "$DropboxDir\Documentation\" -Recurse -Force

# Copy scripts (when they exist)
if (Test-Path "$RepoDir\Scripts") {
    Write-Host "📜 Syncing Scripts..." -ForegroundColor Yellow
    if (Test-Path "$DropboxDir\Scripts") {
        Remove-Item -Path "$DropboxDir\Scripts\*" -Recurse -Force
    }
    if (-not (Test-Path "$DropboxDir\Scripts")) {
        New-Item -ItemType Directory -Path "$DropboxDir\Scripts" -Force | Out-Null
    }
    Copy-Item -Path "$RepoDir\Scripts\*" -Destination "$DropboxDir\Scripts\" -Recurse -Force
}

# Copy ai-agents
Write-Host "🤖 Syncing AI Agents..." -ForegroundColor Yellow
if (Test-Path "$DropboxDir\ai-agents") {
    Remove-Item -Path "$DropboxDir\ai-agents\*" -Recurse -Force
}
if (-not (Test-Path "$DropboxDir\ai-agents")) {
    New-Item -ItemType Directory -Path "$DropboxDir\ai-agents" -Force | Out-Null
}
Copy-Item -Path "$RepoDir\ai-agents\*" -Destination "$DropboxDir\ai-agents\" -Recurse -Force

# Copy runbooks
Write-Host "📖 Syncing Runbooks..." -ForegroundColor Yellow
if (Test-Path "$DropboxDir\runbooks") {
    Remove-Item -Path "$DropboxDir\runbooks\*" -Recurse -Force
}
if (-not (Test-Path "$DropboxDir\runbooks")) {
    New-Item -ItemType Directory -Path "$DropboxDir\runbooks" -Force | Out-Null
}
Copy-Item -Path "$RepoDir\runbooks\*" -Destination "$DropboxDir\runbooks\" -Recurse -Force

# Copy workflows
Write-Host "⚡ Syncing Workflows..." -ForegroundColor Yellow
if (Test-Path "$DropboxDir\workflows") {
    Remove-Item -Path "$DropboxDir\workflows\*" -Recurse -Force
}
if (-not (Test-Path "$DropboxDir\workflows")) {
    New-Item -ItemType Directory -Path "$DropboxDir\workflows" -Force | Out-Null
}
Copy-Item -Path "$RepoDir\workflows\*" -Destination "$DropboxDir\workflows\" -Recurse -Force

# Copy systems
Write-Host "🔧 Syncing Systems..." -ForegroundColor Yellow
if (Test-Path "$DropboxDir\systems") {
    Remove-Item -Path "$DropboxDir\systems\*" -Recurse -Force
}
if (-not (Test-Path "$DropboxDir\systems")) {
    New-Item -ItemType Directory -Path "$DropboxDir\systems" -Force | Out-Null
}
Copy-Item -Path "$RepoDir\systems\*" -Destination "$DropboxDir\systems\" -Recurse -Force

Write-Host "✅ Deployment complete!" -ForegroundColor Green
Write-Host "📁 Files deployed to: $DropboxDir" -ForegroundColor Cyan
