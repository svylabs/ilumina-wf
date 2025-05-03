#!/bin/bash

# Exit immediately on error
set -e

# Check if a directory argument was passed
if [ -z "$1" ]; then
  echo "Usage: ./check_deploy.sh <project_directory>"
  exit 1
fi

# Change to the specified directory
cd "$1"

# Load NVM and switch to Node 20
source ~/.nvm/nvm.sh
nvm use 20

# Run your Hardhat script (edit path as needed)
npx hardhat run simulation/check_deploy.ts
