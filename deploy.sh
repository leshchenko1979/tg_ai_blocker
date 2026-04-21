#!/bin/bash

# Parse command line arguments
SKIP_TESTS=false
while getopts "s" opt; do
  case $opt in
    s) SKIP_TESTS=true ;;
    \?) echo "Invalid option -$OPTARG" >&2; exit 1 ;;
  esac
done

set -e  # Exit on any error

# Color codes and timing functions
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
NC='\033[0m'

start_time=$(date +%s)
section_start_time=0

start_section() {
    section_start_time=$(date +%s)
    echo -e "${BLUE}┌─────────────────────────────────────────────────────────────────┐${NC}"
    echo -e "${BLUE}│${NC} ${WHITE}$1${NC}"
    echo -e "${BLUE}└─────────────────────────────────────────────────────────────────┘${NC}"
}

end_section() {
    local end_time=$(date +%s)
    local duration=$((end_time - section_start_time))
    echo -e "${GREEN}✓ Completed in ${duration}s${NC}"
    echo ""
}

# Load environment variables
if [ ! -f .env ]; then
    echo -e "${RED}Error: .env file not found!${NC}"
    exit 1
fi

source .env

# Validation
: "${REMOTE_USER:?REMOTE_USER not set}"
: "${REMOTE_HOST:?REMOTE_HOST not set}"

start_section "🔧 Code Quality & Testing"

# Run isort to sort imports
echo "Running ruff..."
ruff check --fix src --ignore E402,F403
ruff format src

# Run type checking
echo "Running type checking..."
uvx ty check src

# Run tests if not skipped
if [ "$SKIP_TESTS" = false ]; then
    echo "Running unit tests with SQLite (integration tests are excluded by default)..."
    USE_SQLITE_TESTS=true uv run python -m pytest tests --maxfail=1 --exitfirst --last-failed -q

    if [ $? -ne 0 ]; then
        echo -e "${RED}Tests failed! Aborting deployment.${NC}"
        exit 1
    fi
    echo "All tests completed successfully"
else
    echo "Skipping tests..."
fi

end_section

start_section "📦 File Transfer & Setup"

# Set up directory structure with SSH multiplexing
echo "Setting up directory structure..."
ssh -o ControlMaster=auto -o ControlPath=~/.ssh/master-%r@%h:%p -o ControlPersist=10m ${REMOTE_USER}@${REMOTE_HOST} "
    # Create persistent directories with proper permissions
    mkdir -p ${LOGS_DIR:-/data/projects/ai-antispam/logs}
    chown -R 1000:1000 ${LOGS_DIR:-/data/projects/ai-antispam/logs}
"

# Create package archive
echo "Creating Python package archive..."
TEMP_DIR=$(mktemp -d)
COPYFILE_DISABLE=1 tar \
    --no-xattrs \
    --exclude='venv' \
    --exclude='*.pyc' \
    --exclude='__pycache__' \
    --exclude='.git' \
    --exclude='.pytest_cache' \
    --exclude='node_modules' \
    --exclude='.dockerignore' \
    -czf "$TEMP_DIR/app.tar.gz" src/app/ .dockerfile docker-compose.yml .env pyproject.toml config.yaml PRD.md

# Clean and recreate project directory
echo "Cleaning and recreating project directory..."
ssh -o ControlMaster=auto -o ControlPath=~/.ssh/master-%r@%h:%p -o ControlPersist=10m ${REMOTE_USER}@${REMOTE_HOST} "rm -rf /data/projects/ai-antispam && mkdir -p /data/projects/ai-antispam"

# Copy and extract Python package
echo "Copying and extracting Python package..."
scp "$TEMP_DIR/app.tar.gz" ${REMOTE_USER}@${REMOTE_HOST}:/data/projects/ai-antispam/
ssh -o ControlMaster=auto -o ControlPath=~/.ssh/master-%r@%h:%p -o ControlPersist=10m ${REMOTE_USER}@${REMOTE_HOST} "cd /data/projects/ai-antispam && tar xzf app.tar.gz && rm app.tar.gz && ls -la"
rm -rf "$TEMP_DIR"

end_section

start_section "🐳 Container Deployment"

# Deploy container
echo "Deploying container..."
ssh -o ControlMaster=auto -o ControlPath=~/.ssh/master-%r@%h:%p -o ControlPersist=10m ${REMOTE_USER}@${REMOTE_HOST} '
    cd /data/projects/ai-antispam
    docker compose down --remove-orphans
    docker compose up -d --build
'

end_section

start_section "🏥 Health Verification"

# Wait for container to be healthy
echo "Waiting for container to be healthy..."
ATTEMPTS=0
MAX_ATTEMPTS=30
while [ $ATTEMPTS -lt $MAX_ATTEMPTS ]; do
    if ssh -o ControlMaster=auto -o ControlPath=~/.ssh/master-%r@%h:%p -o ControlPersist=10m ${REMOTE_USER}@${REMOTE_HOST} "cd /data/projects/ai-antispam && docker compose ps --format json | grep -q 'Health.*healthy'"; then
        break
    fi
    ATTEMPTS=$((ATTEMPTS + 1))
    echo "Waiting for container to be healthy (attempt $ATTEMPTS/$MAX_ATTEMPTS)..."
    sleep 5
done

if [ $ATTEMPTS -eq $MAX_ATTEMPTS ]; then
    echo -e "${RED}Container failed to become healthy after ${MAX_ATTEMPTS} attempts${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Container is healthy!${NC}"

end_section

start_section "🧹 Cleanup & Security"

# Clean up old Docker images for this project to prevent disk bloat
echo "Cleaning up old ai-antispam Docker images..."
ssh -o ControlMaster=auto -o ControlPath=~/.ssh/master-%r@%h:%p -o ControlPersist=10m ${REMOTE_USER}@${REMOTE_HOST} "
    # Remove images containing 'ai-antispam' but exclude the currently running image
    docker images --format 'table {{.Repository}}\t{{.ID}}\t{{.CreatedAt}}' | grep ai-antispam | head -n -1 | awk '{print \$2}' | xargs -r docker rmi
"

# Clean up source files after successful deployment
echo "Cleaning up source files on the server (preserving docker-compose and .env for Sablier)..."
ssh -o ControlMaster=auto -o ControlPath=~/.ssh/master-%r@%h:%p -o ControlPersist=10m ${REMOTE_USER}@${REMOTE_HOST} "cd /data/projects/ai-antispam && rm -rf src app"

end_section

# Final deployment summary
end_time=$(date +%s)
total_duration=$((end_time - start_time))
current_time=$(date '+%Y-%m-%d %H:%M:%S')

echo -e "${CYAN}┌─────────────────────────────────────────────────────────────────┐${NC}"
echo -e "${CYAN}│${NC} ${WHITE}🎉 Deployment completed successfully!${NC}"
echo -e "${CYAN}│${NC} ${GREEN}Total deployment time: ${total_duration}s${NC}"
echo -e "${CYAN}│${NC} ${YELLOW}Finished at: ${current_time}${NC}"
echo -e "${CYAN}└─────────────────────────────────────────────────────────────────┘${NC}"
