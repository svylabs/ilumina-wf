# snapshot_generator.py
import json
from .three_stage_llm_call import ThreeStageAnalyzer
from .models import SnapshotCode, Project
import os

class SnapshotGenerator:
    def __init__(self, context):
        self.context = context
        self.analyzer = ThreeStageAnalyzer(SnapshotCode)

    def generate_for_contract(self, contract_name: str):
        # Get contract ABI and info
        artifact_path = self.context.contract_artifact_path(contract_name)
        with open(artifact_path, 'r') as f:
            artifact = json.load(f)
        
        abi = artifact['abi']
        
        prompt = f"""
        Generate TypeScript snapshot code for contract {contract_name} with the following ABI:
        {json.dumps(abi)}
        
        Requirements:
        1. Create a class that implements SnapshotProvider interface
        2. The class should capture all public state variables and view functions
        3. Include proper error handling
        4. Use ethers.js for contract interaction
        5. Generate methods to snapshot all relevant contract data
        6. Return the complete class implementation
        """
        
        snapshot_code = self.analyzer.ask_llm(prompt)
        return snapshot_code

    def generate_all_snapshots(self):
        project = Project.load_summary(self.context.summary_path())
        snapshots = {}
        
        for contract in project.contracts:
            if contract.is_deployable:
                snapshot = self.generate_for_contract(contract.name)
                snapshots[contract.name] = snapshot
        
        return snapshots

    def save_snapshots(self, output_path: str):
        snapshots = self.generate_all_snapshots()
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        with open(output_path, 'w') as f:
            imports = """
            import { ethers } from "ethers";
            import { Contract } from "ethers";
            import { SnapshotProvider } from "@svylabs/ilumina";
            """
            
            f.write(imports + "\n\n")
            
            for contract_name, snapshot in snapshots.items():
                f.write(f"// Snapshot for {contract_name}\n")
                f.write(snapshot.code + "\n\n")
            
            # Generate main provider class
            f.write("""
            export class ContractSnapshotProvider implements SnapshotProvider {
                private contracts: Record<string, Contract>;
                private snapshots: Record<string, any> = {};
                private snapshotImplementations: Record<string, any> = {};

                constructor(contracts: Record<string, Contract>) {
                    this.contracts = contracts;
                    // Initialize snapshot implementations
                    Object.keys(this.contracts).forEach(name => {
                        if (snapshots[name]) {
                            this.snapshotImplementations[name] = new (snapshots[name].constructor)();
                        }
                    });
                }

                async snapshot(): Promise<any> {
                    const results: Record<string, any> = {};
                    
                    for (const [name, contract] of Object.entries(this.contracts)) {
                        if (this.snapshotImplementations[name]) {
                            results[name] = await this.snapshotImplementations[name].snapshot(contract);
                        }
                    }
                    
                    this.snapshots = results;
                    return results;
                }

                getSnapshots() {
                    return this.snapshots;
                }
            }
            """)