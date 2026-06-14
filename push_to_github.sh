#!/usr/bin/env bash
set -euo pipefail

# push_to_github.sh
# Small helper to initialize (if needed), commit, add remote, and push `main`.
# Edit REMOTE_URL below if you prefer SSH or a different repo URL.

REMOTE_URL="https://github.com/clem0g/NVIDIA_Jetson_Nano_AI_Agent_2.0.git"
COMMIT_MSG_INITIAL="Initial import: BuildFindr project + .gitignore"
COMMIT_MSG_UPDATE="Update: local changes committed before push"

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

echo "Working in $ROOT_DIR"

if [ ! -d .git ]; then
  echo "No git repository found — initializing..."
  git init
else
  echo "Git repository found."
fi

# Stage everything
git add .

# Commit: if no commits yet, make initial commit; otherwise commit if changes exist
if ! git rev-parse --verify HEAD >/dev/null 2>&1; then
  echo "Creating initial commit..."
  git commit -m "$COMMIT_MSG_INITIAL"
else
  if [ -n "$(git status --porcelain)" ]; then
    echo "Staging and committing changes..."
    git commit -am "$COMMIT_MSG_UPDATE"
  else
    echo "No changes to commit."
  fi
fi

# Ensure branch named 'main'
git branch -M main

echo "Configuring remote origin -> $REMOTE_URL"
git remote remove origin 2>/dev/null || true
git remote add origin "$REMOTE_URL"

echo "About to push to origin main..."

if command -v gh >/dev/null 2>&1; then
  if gh auth status >/dev/null 2>&1; then
    echo "gh CLI authenticated — pushing..."
    git push -u origin main
  else
    echo "gh CLI detected but not authenticated. Run 'gh auth login' or the push will prompt for credentials."
    git push -u origin main
  fi
else
  echo "gh CLI not found — pushing with git (you may be prompted for credentials)..."
  git push -u origin main
fi

echo "Push complete. Visit: $REMOTE_URL"
