#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────
#  release.sh — Automate versioning, tagging, and GitHub Release
#
#  Usage:
#    ./scripts/release.sh <version>     # e.g. ./scripts/release.sh 0.3.0
#    ./scripts/release.sh patch         # auto-bump patch (0.2.1 → 0.2.2)
#    ./scripts/release.sh minor         # auto-bump minor (0.2.1 → 0.3.0)
#    ./scripts/release.sh major         # auto-bump major (0.2.1 → 1.0.0)
# ────────────────────────────────────────────────────────────────
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}ℹ ${NC}$*"; }
ok()    { echo -e "${GREEN}✅ ${NC}$*"; }
warn()  { echo -e "${YELLOW}⚠️  ${NC}$*"; }
error() { echo -e "${RED}❌ ${NC}$*"; exit 1; }

# ─── Pre-flight checks ──────────────────────────────────────────
command -v gh   >/dev/null 2>&1 || error "gh CLI not installed. Install: https://cli.github.com"
command -v git  >/dev/null 2>&1 || error "git not found"
command -v sed  >/dev/null 2>&1 || error "sed not found"

# Must be on main branch
CURRENT_BRANCH=$(git branch --show-current)
if [[ "$CURRENT_BRANCH" != "main" ]]; then
    error "You must be on the 'main' branch to release. Current: $CURRENT_BRANCH"
fi

# Working tree must be clean
if ! git diff --quiet HEAD 2>/dev/null; then
    error "Working tree is dirty. Commit or stash your changes first."
fi

# Must be up to date with remote
git fetch origin main --quiet
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)
if [[ "$LOCAL" != "$REMOTE" ]]; then
    error "Local main is not up to date with origin/main. Run: git pull origin main"
fi

# ─── Resolve GitHub account ──────────────────────────────────────
# Detect the repo owner to use the correct gh token when multiple
# GitHub accounts are configured.
REPO_FULL=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || true)
if [[ -z "$REPO_FULL" ]]; then
    # Fallback: parse from git remote
    REPO_FULL=$(git remote get-url origin | sed -E 's#.*github\.com[:/](.+)\.git#\1#' | sed 's/\.git$//')
fi
REPO_OWNER=$(echo "$REPO_FULL" | cut -d'/' -f1)
info "Repository: ${YELLOW}${REPO_FULL}${NC}"

# Try to get the token for the repo owner account
GH_TOKEN_CMD="gh auth token -h github.com"
if gh auth token -h github.com -u "$REPO_OWNER" >/dev/null 2>&1; then
    GH_TOKEN_CMD="gh auth token -h github.com -u $REPO_OWNER"
    info "Using gh account: ${YELLOW}${REPO_OWNER}${NC}"
fi
export GH_TOKEN
GH_TOKEN=$($GH_TOKEN_CMD)

# ─── Resolve version ────────────────────────────────────────────
CURRENT_VERSION=$(grep '^version' pyproject.toml | head -1 | sed 's/.*"\(.*\)".*/\1/')
info "Current version in pyproject.toml: ${YELLOW}${CURRENT_VERSION}${NC}"

IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT_VERSION"

if [[ -z "${1:-}" ]]; then
    echo ""
    echo "Usage: $0 <version|patch|minor|major>"
    echo ""
    echo "  $0 patch   →  $MAJOR.$MINOR.$((PATCH + 1))"
    echo "  $0 minor   →  $MAJOR.$((MINOR + 1)).0"
    echo "  $0 major   →  $((MAJOR + 1)).0.0"
    echo "  $0 0.3.0   →  0.3.0"
    exit 1
fi

case "$1" in
    patch) NEW_VERSION="$MAJOR.$MINOR.$((PATCH + 1))" ;;
    minor) NEW_VERSION="$MAJOR.$((MINOR + 1)).0" ;;
    major) NEW_VERSION="$((MAJOR + 1)).0.0" ;;
    *)     NEW_VERSION="$1" ;;
esac

TAG="v${NEW_VERSION}"

# Check tag doesn't already exist
if git tag -l "$TAG" | grep -q "$TAG"; then
    error "Tag $TAG already exists. Choose a different version."
fi

info "New version: ${GREEN}${NEW_VERSION}${NC} (tag: ${GREEN}${TAG}${NC})"
echo ""

# ─── Generate changelog preview ─────────────────────────────────
PREVIOUS_TAG=$(git tag -l --sort=-v:refname "v*" | head -1)
if [[ -n "$PREVIOUS_TAG" ]]; then
    info "Changes since ${PREVIOUS_TAG}:"
    git log --pretty=format:"  - %s (%h)" "${PREVIOUS_TAG}..HEAD" | head -20
    echo ""
fi

echo ""

# ─── Confirm ─────────────────────────────────────────────────────
read -rp "$(echo -e "${YELLOW}Proceed with release ${TAG}? [y/N]${NC} ")" CONFIRM
if [[ "$CONFIRM" != "y" && "$CONFIRM" != "Y" ]]; then
    warn "Aborted."
    exit 0
fi

# ─── Update version in pyproject.toml ────────────────────────────
info "Updating pyproject.toml version to ${NEW_VERSION}..."
sed -i "s/^version = \"${CURRENT_VERSION}\"/version = \"${NEW_VERSION}\"/" pyproject.toml
ok "pyproject.toml updated"

# ─── Commit version bump ────────────────────────────────────────
git add pyproject.toml
git commit -m "chore: bump version to ${NEW_VERSION}"
ok "Version bump committed"

# ─── Push to main ────────────────────────────────────────────────
info "Pushing to origin/main..."
git push origin main
ok "Pushed to main"

# ─── Create and push tag ────────────────────────────────────────
info "Creating tag ${TAG}..."
git tag "$TAG"
git push origin "$TAG"
ok "Tag ${TAG} pushed (triggers PyPI publish via GitHub Actions)"

# ─── Generate changelog for release notes ────────────────────────
if [[ -n "$PREVIOUS_TAG" ]]; then
    CHANGELOG=$(git log --pretty=format:"- %s (%h)" "${PREVIOUS_TAG}..${TAG}" | grep -v "^- chore: bump version")
else
    CHANGELOG=$(git log --pretty=format:"- %s (%h)" "${TAG}" | head -20)
fi

if [[ -z "$CHANGELOG" ]]; then
    CHANGELOG="- Release ${TAG}"
fi

RELEASE_NOTES="## What's Changed

${CHANGELOG}

**Full Changelog**: https://github.com/${REPO_FULL}/compare/${PREVIOUS_TAG:-}...${TAG}"

# ─── Create GitHub Release (set as latest) ───────────────────────
info "Creating GitHub Release ${TAG} (latest)..."
gh release create "$TAG" \
    --repo "$REPO_FULL" \
    --title "KiboUP ${TAG}" \
    --notes "$RELEASE_NOTES" \
    --latest

ok "GitHub Release ${TAG} created and set as latest! 🚀"
echo ""
info "📦 PyPI publish triggered via GitHub Actions"
info "🔗 Release: https://github.com/${REPO_FULL}/releases/tag/${TAG}"
info "⚙️  Actions:  https://github.com/${REPO_FULL}/actions"
