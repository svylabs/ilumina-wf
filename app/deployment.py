from .context import RunContext
from .models import DeploymentInstruction
from .openai import ask_openai
import os
import json

class DeploymentAnalyzer:
    def __init__(self, context: RunContext):
        self.context = context
        self.compiled_contracts = self.load_compiled_contracts()

    # def load_compiled_contracts(self):
    #     compiled_path = self.context.compiled_contracts_path()
    #     if os.path.exists(compiled_path):
    #         with open(compiled_path, "r") as f:
    #             return json.load(f)
    #     print(f"Warning: Compiled contracts not found at {compiled_path}. Proceeding with an empty contract list.")
    #     return {}

    def load_compiled_contracts(self):
        possible_paths = [
            self.context.compiled_contracts_path(),  # Default path
            os.path.join(self.context.cws(), "artifacts/build-info"),  # Hardhat alternate
            os.path.join(self.context.cws(), "build/contracts"),  # Truffle
            os.path.join(self.context.cws(), "out")  # Foundry
        ]
        # Check if the compiled contracts file exists in any of the possible paths
        for path in possible_paths:
            if os.path.exists(path):
                if os.path.isdir(path):
                    # Combine all JSON files in directory
                    combined = {}
                    for root, _, files in os.walk(path):
                        for file in files:
                            if file.endswith('.json'):
                                with open(os.path.join(root, file), 'r') as f:
                                    data = json.load(f)
                                    if 'contractName' in data:
                                        combined[data['contractName']] = data
                    return combined
                else:
                    with open(path, "r") as f:
                        return json.load(f)
        # If no compiled contracts file is found, print a warning and return an empty dictionary
        print(f"Warning: Compiled contracts not found at any standard location. Proceeding with empty contract list.")
        return {}

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
            json.dump([instruction.to_dict() for instruction in instructions], f, indent=2)

    def analyze(self, user_prompt=None):
        deployable_contracts = self.identify_deployable_contracts()
        if not deployable_contracts:
            print("Warning: No deployable contracts found. Proceeding without deployment instructions.")

        readme_path = os.path.join(self.context.project_path(), "README.md")
        deployment_script_path = os.path.join(self.context.project_path(), "scripts/deploy.js")

        readme_content = ""
        if os.path.exists(readme_path):
            with open(readme_path, "r") as f:
                readme_content = f.read()

        deployment_script_content = ""
        if os.path.exists(deployment_script_path):
            with open(deployment_script_path, "r") as f:
                deployment_script_content = f.read()

        prompt = f"""
        The following are the deployable contracts and their ABIs:
        {json.dumps(deployable_contracts)}
        """

        if readme_content:
            prompt += f"\nThe project also contains the following README content:\n{readme_content}"

        if deployment_script_content:
            prompt += f"\nAnd the following deployment script:\n{deployment_script_content}"

        prompt += "\nGenerate deployment instructions for each contract, including constructor arguments if required."

        try:
            _, deployment_instructions = ask_openai(prompt, list[DeploymentInstruction], task="reasoning")

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