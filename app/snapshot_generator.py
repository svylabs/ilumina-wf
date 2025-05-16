# snapshot_generator.py
import json
from .three_stage_llm_call import ThreeStageAnalyzer
from .models import SnapshotCode, Project
import os

class SnapshotGenerator:
    def __init__(self, context):
        self.context = context
        self.analyzer = ThreeStageAnalyzer(SnapshotCode)

    def generate_contract_snapshot(self, contract_name: str):
        """Generate comprehensive contract snapshot code"""
        artifact_path = self.context.contract_artifact_path(contract_name)
        with open(artifact_path, 'r') as f:
            artifact = json.load(f)
        
        abi = artifact['abi']
        
        prompt = f"""
        Generate a complete TypeScript implementation for {contract_name}ContractSnapshot that:
        1. Captures ALL public state variables from the ABI
        2. Properly handles BigNumber conversions
        3. Includes comprehensive error handling
        4. Has proper TypeScript types
        5. Includes detailed JSDoc comments

        ABI:
        {json.dumps(abi, indent=2)}

        Output format:
        ```typescript
        import {{ ethers }} from 'ethers';

        /**
         * @class {contract_name}ContractSnapshot
         * @description Captures all public state of {contract_name} contract
         */
        class {contract_name}ContractSnapshot {{
            /**
             * @method snapshot
             * @description Captures complete contract state
             * @param contract - ethers.Contract instance
             * @returns Promise with all public state variables
             */
            async snapshot(contract: ethers.Contract): Promise<Record<string, any>> {{
                try {{
                    // Implementation that captures ALL state variables
                }} catch (error) {{
                    console.error(`[{contract_name} snapshot error]`, error);
                    throw error;
                }}
            }}
        }}
        ```
        """
        return self.analyzer.ask_llm(prompt)

    def generate_user_snapshot(self, contract_name: str):
        """Generate user-specific snapshot code"""
        artifact_path = self.context.contract_artifact_path(contract_name)
        with open(artifact_path, 'r') as f:
            artifact = json.load(f)
        
        abi = artifact['abi']
        
        prompt = f"""
        Generate a complete TypeScript implementation for {contract_name}UserSnapshot that:
        1. Captures ALL user-specific data from the ABI
        2. Handles multiple user IDs
        3. Properly converts BigNumbers
        4. Includes comprehensive error handling
        5. Has proper TypeScript types
        6. Includes detailed JSDoc comments

        ABI:
        {json.dumps(abi, indent=2)}

        Output format:
        ```typescript
        import {{ ethers }} from 'ethers';

        /**
         * @class {contract_name}UserSnapshot
         * @description Captures user-specific data from {contract_name} contract
         */
        class {contract_name}UserSnapshot {{
            /**
             * @method snapshot
             * @description Captures user-specific data
             * @param contract - ethers.Contract instance
             * @param userIds - Array of user addresses
             * @returns Promise with user data for each user
             */
            async snapshot(contract: ethers.Contract, userIds: string[]): Promise<Array<Record<string, any>>> {{
                const results: Array<Record<string, any>> = [];
                
                try {{
                    // Implementation that captures ALL user-specific data
                }} catch (error) {{
                    console.error(`[{contract_name} user snapshot error]`, error);
                    throw error;
                }}
                
                return results;
            }}
        }}
        ```
        """
        return self.analyzer.ask_llm(prompt)

    def generate_all_snapshots(self):
        project = Project.load_summary(self.context.summary_path())
        return {
            contract.name: {
                'contract': self.generate_contract_snapshot(contract.name),
                'user': self.generate_user_snapshot(contract.name)
            }
            for contract in project.contracts
            if contract.is_deployable
        }

    def save_snapshots(self, output_path: str):
        snapshots = self.generate_all_snapshots()
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        with open(output_path, 'w') as f:
            f.write("""import { SnapshotProvider } from "@svylabs/ilumina";
import { ethers } from 'ethers';

""")
            
            # Write all snapshot classes
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