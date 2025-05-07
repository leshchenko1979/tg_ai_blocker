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

# Load environment variables
if [ ! -f .env ]; then
    echo "Error: .env file not found!"
    exit 1
fi

source .env

echo "Running code quality checks..."

# Run isort to sort imports
echo "Running isort..."
isort src

# Run black for code formatting
echo "Running black..."
black src

# Run tests if not skipped
if [ "$SKIP_TESTS" = false ]; then
    echo "Running tests..."
    #pytest src -v

    # If any of the above commands failed, exit
    if [ $? -ne 0 ]; then
        echo "Tests failed! Aborting deployment."
        exit 1
    fi
else
    echo "Skipping tests..."
fi

# Set up directory structure
echo "Setting up directory structure..."
ssh ${REMOTE_USER}@${REMOTE_HOST} "
    # Create persistent directories with proper permissions
    mkdir -p ${LOGS_DIR:-/home/${REMOTE_USER}/logs}
"

# Create package archive
echo "Creating Python package archive..."
TEMP_DIR=$(mktemp -d)
if [ -f "$TEMP_DIR/app.tar.gz" ]; then
    rm "$TEMP_DIR/app.tar.gz"
fi
tar \
    --exclude='venv' \
    --exclude='*.pyc' \
    --exclude='__pycache__' \
    --exclude='.git' \
    --exclude='.pytest_cache' \
    --exclude='node_modules' \
    --exclude='.dockerfile' \
    --exclude='docker-compose.yml' \
    --exclude='.env' \
    --exclude='.dockerignore' \
    -czf "$TEMP_DIR/app.tar.gz" src/app/

# Clean and recreate project directory
echo "Cleaning and recreating project directory..."
ssh ${REMOTE_USER}@${REMOTE_HOST} "rm -rf ~/tg-ai-blocker && mkdir -p ~/tg-ai-blocker"

# Copy and extract Python package
echo "Copying and extracting Python package..."
scp "$TEMP_DIR/app.tar.gz" ${REMOTE_USER}@${REMOTE_HOST}:~/tg-ai-blocker/
ssh ${REMOTE_USER}@${REMOTE_HOST} "cd ~/tg-ai-blocker && tar xzf app.tar.gz && rm app.tar.gz && ls -la"
rm -rf "$TEMP_DIR"

# Copy configuration files
echo "Copying configuration files..."
scp .dockerfile docker-compose.yml .env requirements.txt config.yaml PRD.md ${REMOTE_USER}@${REMOTE_HOST}:~/tg-ai-blocker/

# Deploy container
echo "Deploying container..."
ssh ${REMOTE_USER}@${REMOTE_HOST} '
    cd ~/tg-ai-blocker
    docker compose down --remove-orphans
    docker compose up -d --build
'

# Check container status
echo "Checking container status..."
ssh ${REMOTE_USER}@${REMOTE_HOST} "docker ps | grep tg-ai-blocker || echo 'Container not found!'"

echo "Deployment completed successfully!"
