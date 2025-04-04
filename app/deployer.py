import json
import subprocess
import os
from typing import Dict, Any
import re
from pathlib import Path
from .models import Contract
from .storage import GCSStorage
from .github import GitHubAPI
import logging

logger = logging.getLogger(__name__)

class ContractDeployer:
    def __init__(self, context):
        self.context = context
        self.gcs = GCSStorage()
        self.github = GitHubAPI()
        self.local_repo_path = f"/tmp/workspace/{self.context.repo_name}"

    def compile_contracts(self) -> Dict[str, Any]:
        """Compile smart contracts using detected dev tool"""
        try:
            # Determine compilation tool
            if self._has_file("hardhat.config.js"):
                return self._compile_with_hardhat()
            elif self._has_file("foundry.toml"):
                return self._compile_with_foundry()
            else:
                raise RuntimeError("No supported build tool detected")

        except Exception as e:
            logger.error(f"Compilation failed: {str(e)}")
            raise

    def _has_file(self, filename: str) -> bool:
        """Check if file exists in repo"""
        return os.path.exists(os.path.join(self.local_repo_path, filename))

    def _compile_with_hardhat(self) -> Dict[str, Any]:
        """Compile contracts using Hardhat"""
        logger.info("Compiling with Hardhat")
        
        result = subprocess.run(
            ["npx", "hardhat", "compile"],
            cwd=self.local_repo_path,
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"Hardhat compilation failed: {result.stderr}")
        
        # Parse compilation artifacts
        artifacts_dir = os.path.join(self.local_repo_path, "artifacts")
        return self._parse_hardhat_artifacts(artifacts_dir)

    def _compile_with_foundry(self) -> Dict[str, Any]:
        """Compile contracts using Foundry"""
        logger.info("Compiling with Foundry")
        
        result = subprocess.run(
            ["forge", "build"],
            cwd=self.local_repo_path,
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"Foundry compilation failed: {result.stderr}")
        
        # Parse compilation artifacts
        artifacts_dir = os.path.join(self.local_repo_path, "out")
        return self._parse_foundry_artifacts(artifacts_dir)

    def _parse_hardhat_artifacts(self, artifacts_dir: str) -> Dict[str, Any]:
        """Parse Hardhat compilation artifacts"""
        contracts = {}
        
        for root, _, files in os.walk(artifacts_dir):
            for file in files:
                if file.endswith(".json") and not file.endswith(".dbg.json"):
                    with open(os.path.join(root, file), "r") as f:
                        artifact = json.load(f)
                        
                        if "abi" in artifact and "bytecode" in artifact:
                            contract_name = file.replace(".json", "")
                            contracts[contract_name] = {
                                "abi": artifact["abi"],
                                "bytecode": artifact["bytecode"],
                                "metadata": artifact.get("metadata", {})
                            }
        
        return {"compiler": "hardhat", "contracts": contracts}

    def _parse_foundry_artifacts(self, artifacts_dir: str) -> Dict[str, Any]:
        """Parse Foundry compilation artifacts"""
        contracts = {}
        
        for file in os.listdir(artifacts_dir):
            if file.endswith(".json") and not file.endswith(".metadata.json"):
                with open(os.path.join(artifacts_dir, file), "r") as f:
                    artifact = json.load(f)
                    
                    if "abi" in artifact and "bytecode" in artifact:
                        contract_name = file.replace(".json", "")
                        contracts[contract_name] = {
                            "abi": artifact["abi"],
                            "bytecode": artifact["bytecode"],
                            "metadata": artifact.get("metadata", {})
                        }
        
        return {"compiler": "foundry", "contracts": contracts}

    def deploy_contracts(self, compiled_data: Dict[str, Any], network: str = "sepolia") -> Dict[str, Any]:
        """Deploy compiled contracts to specified network"""
        try:
            if compiled_data["compiler"] == "hardhat":
                return self._deploy_with_hardhat(network)
            elif compiled_data["compiler"] == "foundry":
                return self._deploy_with_foundry(network)
            else:
                raise RuntimeError("Unsupported compiler for deployment")
        except Exception as e:
            logger.error(f"Deployment failed: {str(e)}")
            raise

    def _deploy_with_hardhat(self, network: str) -> Dict[str, Any]:
        """Deploy using Hardhat"""
        logger.info(f"Deploying with Hardhat to {network}")
        
        result = subprocess.run(
            ["npx", "hardhat", "run", "--network", network, "scripts/deploy.js"],
            cwd=self.local_repo_path,
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"Hardhat deployment failed: {result.stderr}")
        
        # Parse deployment output
        return self._parse_deployment_output(result.stdout)

    def _deploy_with_foundry(self, network: str) -> Dict[str, Any]:
        """Deploy using Foundry"""
        logger.info(f"Deploying with Foundry to {network}")
        
        # First, create deployment script if it doesn't exist
        script_path = os.path.join(self.local_repo_path, "script", "Deploy.sol")
        if not os.path.exists(script_path):
            self._create_foundry_deployment_script()
        
        result = subprocess.run(
            ["forge", "script", "Deploy", "--broadcast", "--rpc-url", network],
            cwd=self.local_repo_path,
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"Foundry deployment failed: {result.stderr}")
        
        # Parse deployment output
        return self._parse_deployment_output(result.stdout)

    def _create_foundry_deployment_script(self):
        """Create basic Foundry deployment script if it doesn't exist"""
        script_content = """// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.13;

import "forge-std/Script.sol";

contract Deploy is Script {
    function run() external {
        vm.startBroadcast();
        // Add your deployment logic here
        vm.stopBroadcast();
    }
}"""
        
        script_dir = os.path.join(self.local_repo_path, "script")
        os.makedirs(script_dir, exist_ok=True)
        
        with open(os.path.join(script_dir, "Deploy.sol"), "w") as f:
            f.write(script_content)

    def _parse_deployment_output(self, output: str) -> Dict[str, Any]:
        """Parse deployment output to extract contract addresses"""
        # This will need to be customized based on your actual deployment output
        addresses = {}
        
        # Simple pattern matching for deployed addresses
        pattern = re.compile(r"Contract\s+(\w+)\s+deployed to:\s+(0x[a-fA-F0-9]{40})")
        matches = pattern.findall(output)
        
        for match in matches:
            addresses[match[0]] = match[1]
        
        return {
            "status": "completed",
            "deployed_contracts": addresses,
            "raw_output": output
        }

    def save_deployment_results(self, deployment_data: Dict[str, Any]):
        """Save deployment results to GCS"""
        self.gcs.write_json(
            f"{self.context.project_root()}/deployment.json",
            deployment_data
        )