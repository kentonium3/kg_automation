# ECI Framework Deployment Script
# Handles git operations and deployment to Dropbox

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoPath = "C:\Users\Kent\Documents\Code\kg_automation"
$DropboxPath = "C:\Users\Kent\Dropbox\Automation"

Write-Host "=== ECI Framework Git & Deployment Script ===" -ForegroundColor Green

# Change to repo directory
Push-Location $RepoPath

try {
    # Git operations
    Write-Host "`n1. Checking git status..." -ForegroundColor Yellow
    & git status
    
    Write-Host "`n2. Adding all new files..." -ForegroundColor Yellow
    & git add .
    
    Write-Host "`n3. Committing changes..." -ForegroundColor Yellow
    & git commit -m "feat: implement ECI automation framework templates

- Updated execution-context-identification.md with standardized MACHINE_ID.txt convention
- Added ECI worker templates for macOS and Windows platforms
- Created VS Code tasks for easy worker installation and execution
- Added .gitignore to protect local identity files
- Implemented job targeting based on requested_executor arrays"
    
    Write-Host "`n4. Pushing to GitHub..." -ForegroundColor Yellow
    & git push origin main
    
    Write-Host "`n5. Deploying to Dropbox..." -ForegroundColor Yellow
    
    # Deploy Documentation
    Copy-Item "$RepoPath\Documentation\execution-context-identification.md" "$DropboxPath\Documentation\" -Force
    Write-Host "   Deployed: execution-context-identification.md"
    
    # Deploy scripts (create directories if needed)
    $DropboxScriptsPath = "$DropboxPath\scripts\templates"
    New-Item -Path $DropboxScriptsPath -ItemType Directory -Force | Out-Null
    
    Copy-Item "$RepoPath\scripts\templates\*" "$DropboxScriptsPath\" -Recurse -Force
    Write-Host "   Deployed: ECI worker templates"
    
    # Deploy VS Code tasks (create directory if needed)
    $DropboxVSCodePath = "$DropboxPath\.vscode"
    New-Item -Path $DropboxVSCodePath -ItemType Directory -Force | Out-Null
    
    Copy-Item "$RepoPath\.vscode\tasks.json" "$DropboxVSCodePath\" -Force
    Write-Host "   Deployed: VS Code tasks"
    
    Write-Host "`n=== Deployment Complete! ===" -ForegroundColor Green
    Write-Host "Repository: $RepoPath" -ForegroundColor Cyan
    Write-Host "Dropbox: $DropboxPath" -ForegroundColor Cyan
    Write-Host "GitHub: https://github.com/your-username/kg-automation" -ForegroundColor Cyan
    
} catch {
    Write-Error "Deployment failed: $($_.Exception.Message)"
} finally {
    Pop-Location
}
