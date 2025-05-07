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
npm install --legacy-peer-deps
npm install --save-dev "@nomicfoundation/hardhat-chai-matchers@^2.0.0" "@nomicfoundation/hardhat-ethers@^3.0.0" "@nomicfoundation/hardhat-network-helpers@^1.0.0" "@types/chai@^4.2.0" "@types/mocha@>=9.1.0" "chai@^4.2.0" "hardhat-gas-reporter@^1.0.8" "solidity-coverage@^0.8.1" "typechain@^8.3.0"
# Run your Hardhat script (edit path as needed)
npx hardhat run --config hardhat.config.ts simulation/check_deploy.ts
