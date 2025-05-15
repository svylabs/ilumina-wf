# snapshot_generator.py
import json
import re
from .three_stage_llm_call import ThreeStageAnalyzer
from .models import SnapshotCode, Project
import os

class SnapshotGenerator:
    def __init__(self, context):
        self.context = context
        self.analyzer = ThreeStageAnalyzer(SnapshotCode)

    def generate_for_contract(self, contract_name: str):
        artifact_path = self.context.contract_artifact_path(contract_name)
        with open(artifact_path, 'r') as f:
            artifact = json.load(f)
        
        abi = artifact['abi']
        
        prompt = f"""
        Generate TypeScript snapshot code for contract {contract_name} with the following ABI:
        {json.dumps(abi)}
        
        Requirements:
        1. Create a class named {contract_name}Snapshot
        2. Must implement async snapshot(contract: Contract, identifiers?: Record<string, string>): Promise<any>
        3. Should capture all relevant contract state based on identifiers if provided
        4. Include proper error handling that returns error information
        5. Use ethers.js Contract type for the parameter
        6. Should not include any import statements
        7. Should handle both view functions and public state variables
        8. Should return an object with the contract's state
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

    def clean_generated_code(self, code: str) -> str:
        """Remove imports and clean up generated code"""
        # Remove all import statements
        code = re.sub(r'^import\s+.+?;\n', '', code, flags=re.MULTILINE)
        # Ensure proper class definition
        if not re.search(r'class\s+\w+Snapshot', code):
            raise ValueError("Generated code doesn't contain required Snapshot class")
        return code.strip()

    def save_snapshots(self, output_path: str):
        snapshots = self.generate_all_snapshots()
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        with open(output_path, 'w') as f:
            # Write standard imports
            f.write("""import { Contract } from "ethers";
import { SnapshotProvider } from "@svylabs/ilumina";

""")
            
            # Write individual snapshot classes
            for contract_name, snapshot in snapshots.items():
                f.write(f"// Snapshot for {contract_name}\n")
                try:
                    clean_code = self.clean_generated_code(snapshot.code)
                    f.write(clean_code + "\n\n")
                except ValueError as e:
                    print(f"Error processing {contract_name} snapshot: {e}")
                    continue
            
            # Generate main provider class with identifiers support
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

    async snapshot(identifiers?: Record<string, string>): Promise<{{
        identifiers: Record<string, string>;
        timestamp: string;
        data: Record<string, any>;
    }}> {{
        const results: Record<string, any> = {{}};
        identifiers = identifiers || {{}};
        
        for (const [name, contract] of Object.entries(this.contracts)) {{
            if (this.snapshotImplementations[name]) {{
                try {{
                    results[name] = await this.snapshotImplementations[name].snapshot(contract, identifiers);
                }} catch (error) {{
                    console.error(`Error taking snapshot for ${{name}}:`, error);
                    results[name] = {{ error: error.message }};
                }}
            }}
        }}
        
        this.snapshots = results;
        return {{
            identifiers,
            timestamp: new Date().toISOString(),
            data: results
        }};
    }}

    getSnapshots() {{
        return this.snapshots;
    }}
}}
""")