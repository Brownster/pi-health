#!/bin/bash

# Pi-Health AI Assistant - Quick Setup Script
# This script sets up the application with minimal configuration required

set -e  # Exit on any error

echo "🚀 Pi-Health AI Assistant - Quick Setup"
echo "======================================"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python 3 is required but not installed.${NC}"
    echo "Please install Python 3 and try again."
    exit 1
fi

echo -e "${BLUE}🐍 Python version:${NC}"
python3 --version

# Check if pip is installed
if ! command -v pip3 &> /dev/null && ! command -v pip &> /dev/null; then
    echo -e "${RED}❌ pip is required but not installed.${NC}"
    echo "Please install pip and try again."
    exit 1
fi

# Use pip3 if available, otherwise pip
PIP_CMD="pip3"
if ! command -v pip3 &> /dev/null; then
    PIP_CMD="pip"
fi

echo -e "${BLUE}📦 Installing Python dependencies...${NC}"
$PIP_CMD install -r requirements.txt

# Create .env file from template if it doesn't exist
if [ ! -f .env ]; then
    echo -e "${BLUE}⚙️  Creating environment configuration...${NC}"
    cp .env.template .env
    echo -e "${GREEN}✅ Created .env file from template${NC}"
else
    echo -e "${YELLOW}⚠️  .env file already exists - skipping template copy${NC}"
fi

# Create logs directory if it doesn't exist
if [ ! -d logs ]; then
    mkdir -p logs
    echo -e "${GREEN}✅ Created logs directory${NC}"
fi

echo ""
echo -e "${GREEN}🎉 Setup completed successfully!${NC}"
echo ""
echo -e "${YELLOW}📋 Next Steps:${NC}"
echo "1. Add your OpenAI API key to the .env file:"
echo "   ${BLUE}OPENAI_API_KEY=your_api_key_here${NC}"
echo ""
echo "2. Start the application:"
echo "   ${BLUE}python3 app.py${NC}"
echo ""
echo "3. Open your browser to:"
echo "   ${BLUE}http://localhost:8100${NC}"
echo ""
echo -e "${BLUE}💡 Tips:${NC}"
echo "• The AI assistant is disabled by default to save resources"
echo "• Enable it from the Settings page once you add your API key"
echo "• Basic system monitoring works without any API key"
echo ""
echo -e "${GREEN}Happy monitoring! 🎯${NC}"