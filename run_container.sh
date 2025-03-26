#!/bin/bash

# Set color output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Default values
PORT=8000
IMAGE_TAG="latest"
CONTAINER_NAME="openmanus"
MODEL=""
BASE_URL=""
API_KEY=""

# Show help information
show_help() {
    echo -e "${BLUE}Usage:${NC}"
    echo "  $0 [options]"
    echo ""
    echo -e "${BLUE}Required Arguments (can be specified as options or positional):${NC}"
    echo "  -m, --model MODEL     LLM model name"
    echo "  -u, --url URL         API base URL"
    echo "  -k, --key KEY         API key for authentication"
    echo ""
    echo -e "${BLUE}Options:${NC}"
    echo "  -h, --help             Show this help message"
    echo "  -p, --port PORT        Specify port to expose (default: 8000)"
    echo "  -t, --tag TAG          Specify docker image tag (default: latest)"
    echo "  -n, --name NAME        Specify container name (default: openmanus)"
    echo "  -r, --restart          Remove existing container if it exists"
    echo ""
    echo -e "${BLUE}Examples:${NC}"
    echo "  # Using named parameters:"
    echo "  $0 -m gpt-4 -u https://api.openai.com/v1 -k sk-xxxx"
    echo "  $0 --model gpt-4 --url https://api.openai.com/v1 --key sk-xxxx"
    echo ""
    echo "  # Using positional parameters (legacy mode):"
    echo "  $0 gpt-4 https://api.openai.com/v1 sk-xxxx"
    echo ""
    echo "  # Combining options:"
    echo "  $0 -p 9000 -t v1.0.0 -m gpt-4 -u https://api.openai.com/v1 -k sk-xxxx"
    echo ""
}

# Parse command line options
RESTART=false
POSITIONAL_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            show_help
            exit 0
            ;;
        -p|--port)
            PORT="$2"
            shift 2
            ;;
        -t|--tag)
            IMAGE_TAG="$2"
            shift 2
            ;;
        -n|--name)
            CONTAINER_NAME="$2"
            shift 2
            ;;
        -r|--restart)
            RESTART=true
            shift
            ;;
        -m|--model)
            MODEL="$2"
            shift 2
            ;;
        -u|--url)
            BASE_URL="$2"
            shift 2
            ;;
        -k|--key)
            API_KEY="$2"
            shift 2
            ;;
        -*)
            echo -e "${RED}Error: Unknown option $1${NC}"
            show_help
            exit 1
            ;;
        *)
            POSITIONAL_ARGS+=("$1")
            shift
            ;;
    esac
done

# Support for legacy positional arguments
if [[ ${#POSITIONAL_ARGS[@]} -gt 0 && -z "$MODEL" ]]; then
    MODEL="${POSITIONAL_ARGS[0]}"
fi

if [[ ${#POSITIONAL_ARGS[@]} -gt 1 && -z "$BASE_URL" ]]; then
    BASE_URL="${POSITIONAL_ARGS[1]}"
fi

if [[ ${#POSITIONAL_ARGS[@]} -gt 2 && -z "$API_KEY" ]]; then
    API_KEY="${POSITIONAL_ARGS[2]}"
fi

# Check required arguments
if [[ -z "$MODEL" || -z "$BASE_URL" || -z "$API_KEY" ]]; then
    echo -e "${RED}Error: Missing required arguments${NC}"
    echo -e "  Model: ${MODEL:-"Not provided"}"
    echo -e "  Base URL: ${BASE_URL:-"Not provided"}"
    echo -e "  API Key: ${API_KEY:-"Not provided"}"
    echo ""
    show_help
    exit 1
fi

# Check if container already exists
CONTAINER_EXISTS=$(docker ps -a -q -f name="^${CONTAINER_NAME}$")
if [ -n "$CONTAINER_EXISTS" ]; then
    if [ "$RESTART" = true ]; then
        echo -e "${YELLOW}Removing existing container...${NC}"
        docker rm -f "$CONTAINER_NAME" > /dev/null 2>&1
        if [ $? -ne 0 ]; then
            echo -e "${RED}Failed to remove existing container${NC}"
            exit 1
        fi
    else
        echo -e "${RED}Error: Container '$CONTAINER_NAME' already exists. Use -r or --restart to replace it.${NC}"
        exit 1
    fi
fi

# Check if image exists
if ! docker image inspect "openmanus:${IMAGE_TAG}" > /dev/null 2>&1; then
    echo -e "${RED}Error: Image 'openmanus:${IMAGE_TAG}' not found. Please build it first.${NC}"
    echo -e "Run: ${YELLOW}./build.sh -t ${IMAGE_TAG}${NC}"
    exit 1
fi

# Display configuration
echo -e "${BLUE}Configuration:${NC}"
echo -e "  Model:       ${GREEN}$MODEL${NC}"
echo -e "  Base URL:    ${GREEN}$BASE_URL${NC}"
echo -e "  Port:        ${GREEN}$PORT${NC}"
echo -e "  Image Tag:   ${GREEN}$IMAGE_TAG${NC}"
echo -e "  Container:   ${GREEN}$CONTAINER_NAME${NC}"
echo ""

# Start container
echo -e "${BLUE}Starting container...${NC}"
docker run -d \
    --name "$CONTAINER_NAME" \
    -p "$PORT:8000" \
    -e LLM_MODEL="$MODEL" \
    -e LLM_BASE_URL="$BASE_URL" \
    -e LLM_API_KEY="$API_KEY" \
    "openmanus:$IMAGE_TAG" \
    python app.py

# Check if container started successfully
if [ $? -eq 0 ]; then
    echo -e "${GREEN}Success! Container is running.${NC}"
    echo -e "API available at: ${GREEN}http://localhost:$PORT${NC}"

    # Show container logs info
    echo -e "\nUse the following command to view logs:"
    echo -e "${YELLOW}docker logs -f $CONTAINER_NAME${NC}"
else
    echo -e "${RED}Failed to start container. Check docker logs for details.${NC}"
    exit 1
fi
