from .context import RunContext
from .models import DeploymentInstruction, Code
from .openai import ask_openai
import os
import json
from .three_stage_llm_call import ThreeStageAnalyzer
import subprocess
import traceback

class DeploymentAnalyzer:
    def __init__(self, context: RunContext):
        self.context = context
        self.compiled_contracts = self.load_compiled_contracts()

    def load_compiled_contracts(self):
        """Search for all JSON files in the artifacts/contracts (Hardhat) or out (Foundry) directory and extract contract data."""
        project_type = self.context.project_type()
        artifacts_root = os.path.join(self.context.cws(), "artifacts/contracts" if project_type == 'hardhat' else "out")

        if not os.path.exists(artifacts_root):
            print(f"Warning: Artifacts directory not found: {artifacts_root}")
            return {}
        
        compiled_contracts = {}
        for root, _, files in os.walk(artifacts_root):
            for file in files:
                if file.endswith(".json") and not file.endswith(".dbg.json") and not file.endswith(".metadata.json"):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, "r") as f:
                            data = json.load(f)

                        # Handle both Hardhat and Foundry artifact formats
                        contract_name = None
                        # Hardhat format
                        if "contractName" in data:
                            contract_name = data["contractName"]
                        # Foundry format
                        elif "abi" in data and project_type == 'foundry':
                            contract_name = os.path.splitext(file)[0]

                        if contract_name:
                            compiled_contracts[contract_name] = data
                    except Exception as e:
                        print(f"Error reading {file_path}: {e}")

        return compiled_contracts

    # def load_compiled_contracts(self):
    #     """Search for all JSON files in the artifacts/contracts directory and extract contract data."""
    #     artifacts_root = os.path.join(self.context.cws(), "artifacts/contracts")
    #     if not os.path.exists(artifacts_root):
    #         print(f"Warning: Artifacts directory not found: {artifacts_root}")
    #         return {}

    #     compiled_contracts = {}
    #     for root, _, files in os.walk(artifacts_root):
    #         for file in files:
    #             if file.endswith(".json"):
    #                 file_path = os.path.join(root, file)
    #                 # print(f"Found JSON file in deployment: {file_path}")  # Print the JSON file path
    #                 try:
    #                     with open(file_path, "r") as f:
    #                         data = json.load(f)
    #                         if "contractName" in data:  # Check for contract metadata
    #                             compiled_contracts[data["contractName"]] = data
    #                 except json.JSONDecodeError:
    #                     print(f"Warning: Failed to parse JSON file: {file_path}")

    #     if not compiled_contracts:
    #         print(f"Warning: No valid contract artifacts found in {artifacts_root}")
    #     return compiled_contracts

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

    def get_prompt_for_refinement(self, project_summary, existing_instructions, user_prompt=None):
        return f"""
        Here is the summary of the smart contract project:
        {json.dumps(project_summary.to_dict())}  

        -----

        Here is the existing deployment instructions in json format:
        {json.dumps(existing_instructions.to_dict())}

        We need to refine the existing deployment instructions based on the user instructions below:
        {user_prompt if user_prompt else "None"}
        """
    
    def get_prompt_for_generating_deployment_instructions(self, project_summary, user_prompt=None):
        return f"""
        Here is the summary of the smart contract project:
        {json.dumps(project_summary.to_dict())}  

        We need to generate deployment instructions for the contracts listed in summary above. The deployment instructions is a sequence of steps to setup the contracts / protocol.

        Let's think step by step:
        1: Based on instructions from the user(provided below), Identify the relevant deployable contracts from the project summary.
        2: Get the constructor for each contract identified in step 1 and identify the parameters needed for deployment.
        3. In case there are function calls needed after deployment(based on user instructions), identify the relevant functions for the contracts identified in step 1.
        4. Based on the functions identified in step3, identify the parameters for those functions.
        5: Repeat step 3-4 for each contract identified in step 1.
        6. Generate the deployment instructions.

        Additional Instructions from user:
        {user_prompt if user_prompt else "None"}
        """


    def analyze(self, user_prompt=None):
        #deployable_contracts = self.identify_deployable_contracts()
        project_summary = self.context.project_summary()

        self.context.deployment_instructions_path()
        existing_instructions = None
        refine = False
        if os.path.exists(self.context.deployment_instructions_path()):
            with open(self.context.deployment_instructions_path(), "r") as f:
                content = json.loads(f.read())
                existing_instructions = DeploymentInstruction.load(content)
                refine = True

        prompt = None
        if refine:
            prompt = self.get_prompt_for_refinement(
                project_summary=project_summary,
                existing_instructions=existing_instructions,
                user_prompt=user_prompt)
        else:
            prompt = self.get_prompt_for_generating_deployment_instructions(
                project_summary=project_summary,
                user_prompt=user_prompt
            )

        #print(f"{prompt}")

        try:
            analyzer = ThreeStageAnalyzer(DeploymentInstruction)
            deployment_instructions = analyzer.ask_llm(prompt)
            #print(f"Deployment instructions: {json.dumps(deployment_instructions.to_dict(), indent=2)}")

            # Save and commit the deployment instructions
            self.save_deployment_instructions(deployment_instructions)
            self.context.commit("Added deployment instructions")
            
            return deployment_instructions

        except Exception as e:
            print(f"Error: Failed to generate deployment instructions: {e}")
            return []
        
    def get_deployment_instructions(self):
        instruction_path = self.context.deployment_instructions_path()
        if os.path.exists(instruction_path):
            with open(instruction_path, "r") as f:
                instructions = json.loads(f.read())
                return DeploymentInstruction.load(instructions)
        else:
            print(f"Warning: Deployment instructions not found at {instruction_path}")
            return None
        
    def get_artifact_imports(self):
        deployment_path = os.path.join(self.context.simulation_path(), "deployment_instructions.json")
        deploy_ts_path = os.path.join(self.context.simulation_path(), "simulation/contracts/deploy.ts")
        instructions = None
        with open(deployment_path, "r") as f:
            instructions = json.load(f)
        
        # Generate imports and artifact loading
        artifacts = {}
        all_contracts = set()

        for step in instructions["sequence"]:
            if step["type"] in ["deploy", "call"]:
                all_contracts.add(step["contract"])

        for contract in sorted(all_contracts):
            artifact_path = self.context.contract_artifact_path(contract)
            # Calculate relative path from deploy.ts to artifact
            rel_path = os.path.relpath(
                artifact_path,
                os.path.dirname(deploy_ts_path)
            ).replace("\\", "/")  # Windows compatibility
            artifacts[contract] = rel_path
        return artifacts
    
    def implement_deployment_script_v2(self):
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
        for step in instructions["sequence"]:
            if step["type"] in ["deploy", "call"]:
                all_contracts.add(step["contract"])

        # Generate imports and artifact loading
        artifact_imports = {}

        for contract in sorted(all_contracts):
            artifact_path = self.context.contract_artifact_path(contract)
            # Calculate relative path from deploy.ts to artifact
            rel_path = os.path.relpath(
                artifact_path,
                os.path.dirname(deploy_ts_path)
            ).replace("\\", "/")  # Windows compatibility
            
            # imports_block.append(f"const {contract}_artifact = require('{rel_path}');\n")
            artifact_imports[contract]=rel_path
        
        prompt = f"""

        Here is the deployment instructions in json format:
        {json.dumps(instructions)}

        Can you implement a deployment module in typescript, using hardhat / ethers.js that will export a async function `deployContracts()`

        The function should be implemented to deploy the contracts in the order specified in the deployment instructions.
        Additionally, the instructions also includes function calls to be made after deployment to setup the contracts correctly.
        The code should not assume a deployment config provided anywhere. It should implement the sequence provided as code.

        The module should also using the correct artifact import paths for the contracts from
        the mapping provided below. The import paths are relative to the deploy.ts file.
        {json.dumps(artifact_imports)}

        And we will use the code similar to below to load the contract from abi / bytecode directly from the imported json files.

        new ethers.ContractFactory(
                    <contract_artifact.json>.abi,
                    <contract_artifact.json>.bytecode,
                    deployer
                );
        """

        guidelines = [
            "0. This is a typescript library / module that need to be exported. So no need for a main function."
            "1. Please make sure the function name is deployContracts() that returns a mapping of all contract references based on defined references as same contract may be deployed multiple times, so need all references. This will be used by other scripts to call the contract.",
            "2. Ensure that all imports for json abi are from the mapping provided",
            "3. Use waitForDeployment() for all contract deployments.",
            "4. use contract.target instead of contract.address to get all contract addresses."
            "5. Ensure that we wait for transaction confirmation. For ex: tx = await contract.connect(user).function_call(params); await tx.wait();"
            "6. The code should not assume a deployment config provided anywhere. It should implement the sequence provided as code."
        ]

        llm = ThreeStageAnalyzer(Code)
        new_code = llm.ask_llm(
            prompt,
            guidelines=guidelines
        )

        with open(self.context.deployment_code_path(), "w") as f:
            f.write(str(new_code.code))

        self.context.commit(new_code.commit_message)

        return deploy_ts_path





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
        for step in instructions["sequence"]:
            if step["type"] in ["deploy", "call"]:
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
        for step in instructions["sequence"]:
            if step["type"] == "deploy":
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
        for step in instructions["sequence"]:
            if step["type"] == "call":
                params = ", ".join([f"contracts.{p['value']}.address" for p in step.get("params", [])])
                transaction_block.append(f"""
        // Configure {step['contract']}.{step['function']}
        await contracts.{step['contract']}.{step['function']}({params});
        console.log(`{step['contract']}.{step['function']} configured`);
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
    
    def verify_deployment_script(self):
        contract_path = self.context.cws()
        # 4. Run the deployment verification
        verification_command = (
            f"./scripts/check_deploy.sh {self.context.simulation_path()}"
        )
        print(f"Running deployment verification command: {verification_command}")
        
        process = subprocess.Popen(
            verification_command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )
        try:
            stdout, stderr = process.communicate(timeout=600)  # 10 minute timeout for deployment
            contract_addresses = {}
            if process.returncode == 0:
                contract_addresses = self._parse_contract_addresses(stdout)
            return process.returncode, contract_addresses, stdout, stderr
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            print(f"Deployment verification timed out: {stderr}")
            return -1, {}, stdout, stderr
        except Exception as e:
            error_trace = traceback.format_exc()
            print(f"Error during deployment verification: {e}")
            return -2, {}, "", ""
        
    def debug_deployment_script(self, step_data, step_status):
        #submission = self.context.get_submission()
        if step_status is not None and step_status.get("status") == "error":
            print(step_data)
            log = step_data.get("log")
            return_code, contract_addresses, stdout, stderr = log[0], log[1], log[2], log[3]
            code = self.context.deployment_code()
            instructions = self.get_deployment_instructions()
            import_prefix = self.context.relative_path_prefix_artifacts(os.path.join(self.context.simulation_path(), "simulation/contracts/deploy.ts"))
            guidelines = [
                "0. This is a typescript library / module that need to be exported. So no need for a main function.",
                "1. Please make sure the function name is deployContracts() that returns a mapping of all contract references based on defined references as same contract may be deployed multiple times, so need all references. This will be used by other scripts to call the contract.",
                "2. Ensure that all imports for json abi are from the mapping provided",
                "3. Use waitForDeployment() for all contract deployments.",
                "4. use contract.target instead of contract.address to get all contract addresses.",
                "5. Ensure that we wait for transaction confirmation. For ex: tx = await contract.connect(user).function_call(params); await tx.wait();"
                "6. As much as possible, keep the code same as the original code and change only the parts that are necessary to fix the error."
                "7. The code should not assume a deployment config provided anywhere. It should implement the sequence provided as code."
            ]
            print(guidelines)
            print(self.get_artifact_imports())
            llm = ThreeStageAnalyzer(Code)
            new_code = llm.ask_llm(
                f"""
                Here is the code for the deployment module:
                {code}

                generated based on the deployment instructions:
                {instructions.to_dict()}

                Here is the error log from the deployment:
                {stderr}

                stdout from the deployment:
                {stdout}

                Here is a mapping of artifact import paths for the contracts.
                {json.dumps(self.get_artifact_imports())}

                Please analyze the code and provide updated code to fix the error.
                1. Please make sure the function name is deployContracts() that returns a mapping of all contract and contract object. This will be used by other scripts to call the contract.
                2. Ensure that all imports for json are from the provided mapping, including relative paths as we refer to a different repo for ABI json.
                3. Use waitForDeployment() for all contract deployments.
                4. use contract.target instead of contract.address to get all contract addresses.
                5. As much as possible, keep the code same as the original code and change only the parts that are necessary to fix the error.
                6. Ensure that we wait for transaction confirmation. For ex: tx = await contract.connect(user).function_call(params); await tx.wait();"
                """
                ,
                guidelines=guidelines
            )

            # Save the new code
            with open(self.context.deployment_code_path(), "w") as f:
                #print(new_code.code)
                f.write(str(new_code.code))
            
            self.context.commit(new_code.commit_message)
            return new_code

        else:
            # Nothing to debug
            pass


    def _parse_contract_addresses(self, output):
        """Parse contract addresses from deployment output"""
        addresses = {}
        for line in output.split('\n'):
            if 'DeployedContract-' in line:
                parts = line.split('DeployedContract-')
                #print(f"Parsing line: {line.strip()}")
                if len(parts) == 2:
                    name = parts[1].split(":")[0].strip()
                    address = parts[1].split(":")[1].strip()
                    addresses[name] = address
        return addresses

        
        