from .context import RunContext
from .models import DeploymentInstruction
from .openai import ask_openai
import os
import json

class DeploymentAnalyzer:
    def __init__(self, context: RunContext):
        self.context = context
        self.compiled_contracts = self.load_compiled_contracts()

    def load_compiled_contracts(self):
        """Search for all JSON files in the artifacts/contracts directory and extract contract data."""
        artifacts_root = os.path.join(self.context.cws(), "artifacts/contracts")
        if not os.path.exists(artifacts_root):
            print(f"Warning: Artifacts directory not found: {artifacts_root}")
            return {}

        compiled_contracts = {}
        for root, _, files in os.walk(artifacts_root):
            for file in files:
                if file.endswith(".json"):
                    file_path = os.path.join(root, file)
                    # print(f"Found JSON file in deployment: {file_path}")  # Print the JSON file path
                    try:
                        with open(file_path, "r") as f:
                            data = json.load(f)
                            if "contractName" in data:  # Check for contract metadata
                                compiled_contracts[data["contractName"]] = data
                    except json.JSONDecodeError:
                        print(f"Warning: Failed to parse JSON file: {file_path}")

        if not compiled_contracts:
            print(f"Warning: No valid contract artifacts found in {artifacts_root}")
        return compiled_contracts

    def identify_deployable_contracts(self):
        deployable_contracts = []
        for contract_name, contract_data in self.compiled_contracts.items():
            if "constructor" in contract_data.get("abi", []):
                deployable_contracts.append({
                    "contract_name": contract_name,
                    "abi": contract_data["abi"]
                })
        return deployable_contracts
    
    def save_deployment_instructions(self, instructions):
        """Save deployment instructions to a JSON file in the simulation repo"""
        deployment_path = os.path.join(self.context.simulation_path(), "deployment_instructions.json")
        with open(deployment_path, 'w') as f:
            json.dump(instructions.to_dict(), f, indent=2)

    def analyze(self, user_prompt=None):
        #deployable_contracts = self.identify_deployable_contracts()
        project_summary = self.context.project_summary()
        
        prompt = f"""
        Here is the summary of the smart contract project:
        {json.dumps(project_summary.to_dict())}  

        Can you generate deployment instructions for the contracts above. The deployment instructions is a sequence of steps to setup the contracts / protocol.

        Guidelines:
        1. Not all contracts are deployable.
        2. Some contracts require constructor arguments and should match the constructor parameters of the contract available in the project summary.
        3. Some contracts may require additional function call after deployment.
        4. Try to infer the parameters from it's names of the constructor in project summary / contracts or the contract calls.
        5. In the function attribute in result, just use the function name, without braces or parameters.
        6. If the type is deploy, give it a name in ref_name that can be used as a variable name, and point the "ref" to use these names.

        Additional instructions from user:
        {user_prompt if user_prompt else "None"}
        """

        print(f"{user_prompt}")

        try:
            _, deployment_instructions = ask_openai(prompt, DeploymentInstruction, task="reasoning")

            # Save and commit the deployment instructions
            self.save_deployment_instructions(deployment_instructions)
            self.context.commit("Added deployment instructions")
            
            return deployment_instructions

        except Exception as e:
            print(f"Error: Failed to generate deployment instructions: {e}")
            return []

    def implement_deployment_script(self):
        deployment_path = os.path.join(self.context.simulation_path(), "deployment_instructions.json")
        deploy_ts_path = os.path.join(self.context.simulation_path(), "simulation/contracts/deploy.ts")
        
        if not os.path.exists(deployment_path):
            raise FileNotFoundError(f"Missing deployment instructions at {deployment_path}")
        if not os.path.exists(deploy_ts_path):
            raise FileNotFoundError(f"Missing deploy.ts template at {deploy_ts_path}")

        with open(deployment_path, "r") as f:
            instructions = json.load(f)

        # Read existing deploy.ts template
        with open(deploy_ts_path, "r") as f:
            template = f.read()

        # Track all unique contracts we need artifacts for
        all_contracts = set()
        for step in instructions["DeploymentInstruction"]["sequence"]:
            if step["type"] in ["contract", "transaction"]:
                all_contracts.add(step["contract"])

        # Generate imports and artifact loading
        imports_block = []
        artifact_loading = []

        for contract in sorted(all_contracts):
            try:
                artifact_path = self.context.contract_artifact_path(contract)
                # Calculate relative path from deploy.ts to artifact
                rel_path = os.path.relpath(
                    artifact_path,
                    os.path.dirname(deploy_ts_path)
                ).replace("\\", "/")  # Windows compatibility
                
                # imports_block.append(f"const {contract}_artifact = require('{rel_path}');\n")
                imports_block.append(f"import {contract}_artifact from '{rel_path}';\n")
                artifact_loading.append(f"""    if (!{contract}_artifact) {{
                    throw new Error(`Missing artifact for {contract}`);
                }}
                """)
            except FileNotFoundError as e:
                print(e)

        # Generate DEPLOY_BLOCK content
        deploy_block = []
        for step in instructions["DeploymentInstruction"]["sequence"]:
            if step["type"] == "contract":
                contract_name = step["contract"]
                params = ", ".join([str(p["value"]) for p in step.get("params", [])])
                
                deploy_block.append(f"""
        // Deploy {contract_name}
        const {contract_name}_factory = new ethers.ContractFactory(
            {contract_name}_artifact.abi,
            {contract_name}_artifact.bytecode,
            deployer
        );
        contracts.{contract_name} = await {contract_name}_factory.deploy({params});
        await contracts.{contract_name}.waitForDeployment();
        console.log(`{contract_name} deployed to: ${{await contracts.{contract_name}.getAddress()}}`);
    """)

        # Generate TRANSACTION_BLOCK content
        transaction_block = []
        for step in instructions["DeploymentInstruction"]["sequence"]:
            if step["type"] == "transaction":
                params = ", ".join([f"contracts.{p['value']}.address" for p in step.get("params", [])])
                transaction_block.append(f"""
        // Configure {step['contract']}.{step['method']}
        await contracts.{step['contract']}.{step['method']}({params});
        console.log(`{step['contract']}.{step['method']} configured`);
    """)

        # Generate MAPPING_BLOCK content
        mapping_block = """
        // Final contract addresses
        console.log("\\n=== Deployment Summary ===");
        for (const [name, contract] of Object.entries(contracts)) {
            console.log(`${name}: ${await contract.getAddress()}`);
        }
    """

        # Build the complete file content
        updated_code = template.replace(
            "// IMPORT_BLOCK - Auto-generated contract imports",
            "".join(imports_block).strip()
        ).replace(
            "// ARTIFACT_LOAD_BLOCK - Auto-generated artifact validation",
            "".join(artifact_loading).strip()
        ).replace(
            "// DEPLOY_BLOCK - Auto-generated contract deployments",
            "".join(deploy_block).strip()
        ).replace(
            "// TRANSACTION_BLOCK - Auto-generated contract configurations",
            "".join(transaction_block).strip()
        ).replace(
            "// MAPPING_BLOCK - Auto-generated address mappings",
            mapping_block.strip()
        )

        # Write the updated file
        with open(deploy_ts_path, "w") as f:
            f.write(updated_code)

        self.context.commit("Updated deploy.ts with generated deployment blocks")
        return deploy_ts_path