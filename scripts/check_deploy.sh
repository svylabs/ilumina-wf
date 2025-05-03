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
npm install --legacy-peer-deps
npm install --save-dev @nomicfoundation/hardhat-ignition-ethers @nomicfoundation/hardhat-ignition @nomicfoundation/ignition-core @nomicfoundation/hardhat-verify @typechain/ethers-v6 ethers --legacy-peer-deps

# Run your Hardhat script (edit path as needed)
npx hardhat run simulation/check_deploy.ts
