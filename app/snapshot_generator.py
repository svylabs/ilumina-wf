# snapshot_generator.py
import json
from typing import Dict, Any
from .three_stage_llm_call import ThreeStageAnalyzer
from .models import SnapshotCode, Project
import os

class SnapshotGenerator:
    def __init__(self, context):
        self.context = context
        self.analyzer = ThreeStageAnalyzer(SnapshotCode)

    def _generate_snapshot_class(self, contract_name: str, snapshot_type: str, abi: Dict[str, Any]) -> str:
        """Core method to generate snapshot class implementations"""
        is_user_snapshot = snapshot_type == "user"
        
        prompt = f"""
        Generate a complete, production-ready TypeScript implementation for {contract_name}{snapshot_type.capitalize()}Snapshot.
        
        Requirements:
        1. Must properly handle BigNumber conversions to string
        2. Must include comprehensive error handling with detailed error messages
        3. Must have proper TypeScript types for all inputs and outputs
        4. Must include detailed JSDoc comments
        5. Must avoid duplicate imports
        6. Must use async/await properly
        7. Must include all relevant state variables/functions from the ABI
        8. Must import BigNumber from 'bignumber.js' if BigNumber is required
        9. Must never use ethers.utils — use ethers.isAddress and other helpers directly from ethers
        
        For {"user" if is_user_snapshot else "contract"} snapshots:
        - {"Must handle multiple user IDs and user-specific data" if is_user_snapshot else "Must capture all public state variables"}
        - {"Must optimize calls to avoid redundant contract calls" if is_user_snapshot else ""}
        
        Contract ABI:
        {json.dumps(abi, indent=2)}
        
        Output only the complete class implementation in the following format:
        
        import {{ ethers }} from 'ethers';
        import BigNumber from 'bignumber.js';

        /**
         * @class {contract_name}{snapshot_type.capitalize()}Snapshot
         * @description {"Captures user-specific data from " if is_user_snapshot else "Captures all public state of "}{contract_name} contract
         */
        class {contract_name}{snapshot_type.capitalize()}Snapshot {{
            /**
             * @method snapshot
             * @description {"Captures user-specific data" if is_user_snapshot else "Captures complete contract state"}
             * @param contract - ethers.Contract instance
             {"* @param userIds - Array of user addresses" if is_user_snapshot else ""}
             * @returns Promise with {"user data for each user" if is_user_snapshot else "all public state variables"}
             */
            async snapshot(
                contract: ethers.Contract{"",
                {"userIds: string[]," if is_user_snapshot else ""}}
            ): Promise<{"Array<Record<string, any>>" if is_user_snapshot else "Record<string, any>"}> {{
                // Implementation goes here
            }}
        }}
        """
        
        return self.analyzer.ask_llm(prompt)

    def generate_contract_snapshot(self, contract_name: str) -> SnapshotCode:
        """Generate contract state snapshot implementation"""
        artifact_path = self.context.contract_artifact_path(contract_name)
        with open(artifact_path, 'r') as f:
            artifact = json.load(f)
        return self._generate_snapshot_class(contract_name, "contract", artifact['abi'])

    def generate_user_snapshot(self, contract_name: str) -> SnapshotCode:
        """Generate user-specific snapshot implementation"""
        artifact_path = self.context.contract_artifact_path(contract_name)
        with open(artifact_path, 'r') as f:
            artifact = json.load(f)
        return self._generate_snapshot_class(contract_name, "user", artifact['abi'])

    def generate_all_snapshots(self) -> Dict[str, Dict[str, SnapshotCode]]:
        """Generate all snapshots for the project"""
        project = Project.load_summary(self.context.summary_path())
        return {
            contract.name: {
                "contract": self.generate_contract_snapshot(contract.name),
                "user": self.generate_user_snapshot(contract.name)
            }
            for contract in project.contracts
            if contract.is_deployable
        }

    def save_snapshots(self, output_path: str) -> None:
        """Save all generated snapshots to a file"""
        snapshots = self.generate_all_snapshots()
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        with open(output_path, 'w') as f:
            # Write header and imports
            f.write("""import { SnapshotProvider } from "@svylabs/ilumina";
import { ethers, BigNumber } from 'ethers';

""")
            
            # Write all snapshot implementations
            for contract_name, snapshot_types in snapshots.items():
                for snapshot_type, snapshot in snapshot_types.items():
                    f.write(f"// {snapshot_type.capitalize()} Snapshot for {contract_name}\n")
                    f.write(snapshot.code + "\n\n")
            
            # Generate provider class
            f.write("""
interface ContractSnapshotResult {
    timestamp: string;
    data: Record<string, any>;
}

interface UserSnapshotResult {
    userIds: string[];
    timestamp: string;
    data: Record<string, any>;
}

export class ContractSnapshotProvider implements SnapshotProvider {
    private contracts: Record<string, ethers.Contract>;
    private contractSnapshots: Record<string, any> = {};
    private userSnapshots: Record<string, any> = {};

    constructor(contracts: Record<string, ethers.Contract>) {
        this.contracts = contracts;
""")
            
            # Add initialization code
            for contract_name in snapshots.keys():
                f.write(f"        this.contractSnapshots['{contract_name}'] = new {contract_name}ContractSnapshot();\n")
                f.write(f"        this.userSnapshots['{contract_name}'] = new {contract_name}UserSnapshot();\n")
            
            # Complete provider implementation
            f.write("""
    }

    async contractSnapshot(): Promise<ContractSnapshotResult> {
        const results: Record<string, any> = {};
        
        for (const [name, contract] of Object.entries(this.contracts)) {
            if (this.contractSnapshots[name]) {
                try {
                    results[name] = await this.contractSnapshots[name].snapshot(contract);
                } catch (error) {
                    results[name] = { 
                        error: error instanceof Error ? {
                            message: error.message,
                            stack: error.stack
                        } : {
                            message: String(error),
                            stack: undefined
                        }
                    };
                }
            }
        }
        
        return {
            timestamp: new Date().toISOString(),
            data: results
        };
    }

    async userSnapshot(userIds: string[]): Promise<UserSnapshotResult> {
        if (!userIds || userIds.length === 0) {
            throw new Error("userIds array must contain at least one user address");
        }

        const results: Record<string, any> = {};
        
        for (const [name, contract] of Object.entries(this.contracts)) {
            if (this.userSnapshots[name]) {
                try {
                    results[name] = await this.userSnapshots[name].snapshot(contract, userIds);
                } catch (error) {
                    results[name] = {
                        error: error instanceof Error ? {
                            message: error.message,
                            stack: error.stack
                        } : {
                            message: String(error),
                            stack: undefined
                        }
                    };
                }
            }
        }
        
        return {
            userIds,
            timestamp: new Date().toISOString(),
            data: results
        };
    }
}
""")