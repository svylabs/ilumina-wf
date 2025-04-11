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

    def analyze(self):
        deployable_contracts = self.identify_deployable_contracts()
        if not deployable_contracts:
            print("Warning: No deployable contracts found. Proceeding without deployment instructions.")
            # return DeploymentInstruction(sequence=[])

        readme_path = os.path.join(self.context.project_path(), "README.md")
        deployment_script_path = os.path.join(self.context.project_path(), "scripts/deploy.js")

        readme_content = ""
        if os.path.exists(readme_path):
            with open(readme_path, "r") as f:
                readme_content = f.read()
        else:
            print(f"Warning: README.md not found at {readme_path}. Proceeding without README content.")

        deployment_script_content = ""
        if os.path.exists(deployment_script_path):
            with open(deployment_script_path, "r") as f:
                deployment_script_content = f.read()
        else:
            print(f"Warning: Deployment script not found at {deployment_script_path}. Proceeding without deployment script content.")

        prompt = f"""
        The following are the deployable contracts and their ABIs:
        {json.dumps(deployable_contracts)}

        {'The project also contains the following README content:\n' + readme_content if readme_content else 'No README content available.'}

        {'And the following deployment script:\n' + deployment_script_content if deployment_script_content else 'No deployment script available.'}

        Generate deployment instructions for each contract, including constructor arguments if required.
        """

        try:
            _, deployment_instructions = ask_openai(prompt, list[DeploymentInstruction], task="reasoning")
            # if not deployment_instructions:
            #     print("Warning: No deployment instructions generated.")
            #     return DeploymentInstruction(sequence=[])

        except Exception as e:
            print(f"Error: Failed to generate deployment instructions: {e}")
            # return DeploymentInstruction(sequence=[])
            deployment_instructions = []

        return deployment_instructions
