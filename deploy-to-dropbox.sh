#!/bin/bash
# Deploy committed files from git repository to Dropbox

# Set paths
REPO_DIR="$HOME/Documents/Code/kg-automation"
DROPBOX_DIR="$HOME/Library/CloudStorage/Dropbox/Automation"

echo "🚀 Deploying kg-automation to Dropbox..."

# Copy bootstrap file to top-level (critical for AI sessions)
echo "🎯 Syncing Bootstrap to Top-Level..."
cp "$REPO_DIR/ai-agents/ai-context-bootstrap.md" "$DROPBOX_DIR/ai-agents/ai-context-bootstrap.md"

# Copy documentation
echo "📚 Syncing Documentation..."
rsync -av --delete "$REPO_DIR/Documentation/" "$DROPBOX_DIR/Documentation/"

# Copy scripts (when they exist)
if [ -d "$REPO_DIR/Scripts" ]; then
    echo "📜 Syncing Scripts..."
    rsync -av --delete "$REPO_DIR/Scripts/" "$DROPBOX_DIR/Scripts/"
fi

# Copy ai-agents
echo "🤖 Syncing AI Agents..."
rsync -av --delete "$REPO_DIR/ai-agents/" "$DROPBOX_DIR/ai-agents/"

# Copy runbooks  
echo "📖 Syncing Runbooks..."
rsync -av --delete "$REPO_DIR/runbooks/" "$DROPBOX_DIR/runbooks/"

# Copy workflows
echo "⚡ Syncing Workflows..."
rsync -av --delete "$REPO_DIR/workflows/" "$DROPBOX_DIR/workflows/"

# Copy systems
echo "🔧 Syncing Systems..."
rsync -av --delete "$REPO_DIR/systems/" "$DROPBOX_DIR/systems/"

echo "✅ Deployment complete!"
echo "📁 Files deployed to: $DROPBOX_DIR"
