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
        1. Create a class named {contract_name}Snapshot with a single method: snapshot(contract: Contract)
        2. The method should return a Promise<any> with all relevant contract state
        3. Include proper error handling
        4. Use ethers.js Contract type for the parameter
        5. Should not include constructor - we'll call it with existing contract instance
        6. Should capture all public state variables and view functions
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
            # Write imports
            f.write("""import { Contract } from "ethers";
import { SnapshotProvider } from "@svylabs/ilumina";

""")
            
            # Write individual snapshot classes
            for contract_name, snapshot in snapshots.items():
                f.write(f"// Snapshot for {contract_name}\n")
                f.write(snapshot.code + "\n\n")
            
            # Generate main provider class
            implementations = "\n        ".join(
                f"this.snapshotImplementations['{name}'] = new {name}Snapshot();"
                for name in snapshots.keys()
            )
            
            f.write(f"""
export class ContractSnapshotProvider implements SnapshotProvider {{
    private contracts: Record<string, Contract>;
    private snapshots: Record<string, any> = {{}};
    private snapshotImplementations: Record<string, any> = {{}};

    constructor(contracts: Record<string, Contract>) {{
        this.contracts = contracts;
        // Initialize snapshot implementations
        {implementations}
    }}

    async snapshot(): Promise<any> {{
        const results: Record<string, any> = {{}};
        
        for (const [name, contract] of Object.entries(this.contracts)) {{
            if (this.snapshotImplementations[name]) {{
                results[name] = await this.snapshotImplementations[name].snapshot(contract);
            }}
        }}
        
        this.snapshots = results;
        return results;
    }}

    getSnapshots() {{
        return this.snapshots;
    }}
}}
""")