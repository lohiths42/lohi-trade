#!/bin/bash
# LOHI-TRADE Prerequisite Checker
# Aborts with a clear message if required system binaries are missing.

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

echo "Checking system prerequisites for LOHI-TRADE..."

MISSING=0

check_binary() {
    if ! command -v "$1" &> /dev/null; then
        echo -e "${RED}✘ $2 is not installed.${NC}"
        MISSING=$((MISSING + 1))
    else
        echo -e "${GREEN}✔ $2 is installed.${NC}"
    fi
}

check_binary "python3" "Python 3"
check_binary "docker" "Docker"
check_binary "node" "Node.js"
check_binary "npm" "npm"
check_binary "git" "Git"
check_binary "curl" "Curl"
check_binary "lsof" "lsof"

if [ $MISSING -gt 0 ]; then
    echo ""
    echo -e "${RED}Total missing dependencies: $MISSING${NC}"
    echo "Please install the missing tools listed above and try again."
    exit 1
fi

echo ""
echo -e "${GREEN}All system prerequisites met!${NC}"
exit 0
