#!/bin/bash

# Set color output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Show help information
show_help() {
    echo -e "${BLUE}Usage:${NC}"
    echo "  ./build.sh [options]"
    echo ""
    echo -e "${BLUE}Options:${NC}"
    echo "  -h, --help     Show help information"
    echo "  -a, --arch     Specify build architecture (arm64 or amd64)"
    echo "  -t, --tag      Specify image tag (default: latest)"
    echo ""
    echo -e "${BLUE}Examples:${NC}"
    echo "  ./build.sh                  # Auto-detect architecture and build"
    echo "  ./build.sh -a arm64         # Build for ARM64 architecture"
    echo "  ./build.sh -a amd64         # Build for AMD64 architecture"
    echo "  ./build.sh -t v1.0.0        # Build with specific tag"
    echo ""
}

# Detect system architecture
detect_arch() {
    local arch=$(uname -m)
    case "$arch" in
        "x86_64")
            echo "amd64"
            ;;
        "arm64")
            echo "arm64"
            ;;
        *)
            echo -e "${RED}Error: Unsupported architecture $arch${NC}"
            exit 1
            ;;
    esac
}

# Validate architecture parameter
validate_arch() {
    local arch=$1
    if [[ "$arch" != "arm64" && "$arch" != "amd64" ]]; then
        echo -e "${RED}Error: Invalid architecture '$arch'. Must be 'arm64' or 'amd64'${NC}"
        exit 1
    fi
}

# Initialize default values
ARCH=$(detect_arch)
TAG="latest"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            show_help
            exit 0
            ;;
        -a|--arch)
            ARCH="$2"
            validate_arch "$ARCH"
            shift 2
            ;;
        -t|--tag)
            TAG="$2"
            shift 2
            ;;
        *)
            echo -e "${RED}Error: Unknown parameter $1${NC}"
            show_help
            exit 1
            ;;
    esac
done

# Display build information
echo -e "${BLUE}Build Information:${NC}"
echo -e "Architecture: ${GREEN}$ARCH${NC}"
echo -e "Tag: ${GREEN}$TAG${NC}"
echo ""

# Build Docker image
echo -e "${BLUE}Starting Docker image build...${NC}"
docker build \
    --platform linux/$ARCH \
    -t cloud-manus:$TAG \
    --build-arg ARCH=$ARCH \
    .

# Check build result
if [ $? -eq 0 ]; then
    echo -e "${GREEN}Build successful!${NC}"
    echo -e "Image info: cloud-manus:$TAG ($ARCH)"
else
    echo -e "${RED}Build failed!${NC}"
    exit 1
fi
