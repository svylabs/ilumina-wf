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
        compiled_path = self.context.compiled_contracts_path()
        if os.path.exists(compiled_path):
            with open(compiled_path, "r") as f:
                return json.load(f)
        print(f"Warning: Compiled contracts not found at {compiled_path}. Proceeding with an empty contract list.")
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

    def analyze(self):
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

    def generate_deploy_ts(self):
        """Generates contracts/deploy.ts from deployment_instructions.json"""
        deployment_path = os.path.join(self.context.simulation_path(), "deployment_instructions.json")
        deploy_ts_path = os.path.join(self.context.simulation_path(), "contracts/deploy.ts")

        if not os.path.exists(deployment_path):
            print(f"Error: {deployment_path} not found. Cannot generate deploy.ts.")
            return

        with open(deployment_path, "r") as f:
            deployment_instructions = json.load(f)

        prompt = f"""
        Using the following deployment instructions:
        {json.dumps(deployment_instructions, indent=2)}

        Generate a TypeScript file for deploying the contracts. The file should:
        - Import necessary libraries like ethers.js.
        - Iterate over the deployment instructions.
        - Deploy each contract with the specified constructor arguments.
        - Log the deployed contract addresses.
        """

        try:
            # Generate and sanitize code
            # _, raw_code = ask_openai(prompt, str, task="code-generation")
            # code = raw_code.strip().removeprefix("```typescript").removesuffix("```").strip()
            
            deploy_ts_content = ask_openai(prompt, str, task="code-generation")
            os.makedirs(os.path.dirname(deploy_ts_path), exist_ok=True)

            # Write file
            with open(deploy_ts_path, "w") as f:
                # f.write(code)
                f.write(deploy_ts_content)
            print(f"Generated deploy.ts at {deploy_ts_path}")

            self.context.commit("Added generated deploy.ts")
            return deploy_ts_path
        
        except Exception as e:
            print(f"Error: Failed to generate deploy.ts: {e}")

