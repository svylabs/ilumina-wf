#!/bin/bash

# Exit immediately on error
set -e

# Check if a directory argument was passed
if [ -z "$1" ]; then
  echo "Usage: ./compile_contracts.sh <project_directory>"
  exit 1
fi

echo "Compiling contracts in directory: $1"
echo "Using Hardhat config file: $2"

# Change to the specified directory
cd "$1"

rm -rf package-lock.json

# Load NVM and switch to Node 20
npm install --legacy-peer-deps
npm install --save-dev hardhat @nomicfoundation/hardhat-toolbox @nomicfoundation/hardhat-ignition-ethers @nomicfoundation/hardhat-ignition @nomicfoundation/ignition-core @nomicfoundation/hardhat-verify @typechain/ethers-v6 ethers --legacy-peer-deps
#npm install -i --save-dev --force hardhat @nomicfoundation/hardhat-toolbox @nomicfoundation/hardhat-ignition-ethers @nomicfoundation/hardhat-ignition @nomicfoundation/ignition-core @nomicfoundation/hardhat-verify @typechain/ethers-v6 ethers

# Run your Hardhat script (edit path as needed)
npx hardhat compile --config "$2"
