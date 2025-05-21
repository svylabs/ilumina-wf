import os
from openai import OpenAI
import json
from .models import Contract, Project
from .models import extract_solidity_functions_and_contract_name, extract_all_solidity_definitions
from .openai import ask_openai
from .three_stage_llm_call import ThreeStageAnalyzer

class ProjectSummarizer:
    def __init__(self, context):
        self.context = context
    
    def find_dev_tool(self):
        if (os.path.exists(self.context.cws() + "/package.json")) and (
            (os.path.exists(self.context.cws() + "/hardhat.config.js") or 
             os.path.exists(self.context.cws() + "/hardhat.config.ts"))):
            return "hardhat"
        elif os.path.exists(self.context.cws() + "/foundry.toml"):
            return "foundry"
        raise Exception("Cannot find development tool")

    def find_contracts(self):
        base_contract_path = self.context.cws() + "/contracts"
        if self.find_dev_tool() == "hardhat":
            base_contract_path = self.context.cws() + "/contracts"
        elif self.find_dev_tool() == "foundry":
            base_contract_path = self.context.cws() + "/src"
        contracts = []
        for root, dirs, files in os.walk(base_contract_path):
            for file in files:
                if file.endswith(".sol"):
                    content = ""
                    with open(os.path.join(root, file), "r") as f:
                        content = f.read()
                    if (content.strip() == ""):
                        continue
                    contracts.append(
                        {
                            "path": os.path.join(root, file),
                            "name": file,
                            "content": content
                        }
                    )
        return contracts

    def prepare(self):
        print("Analyzing the repository")
        self.dev_tool = self.find_dev_tool()
        self.contracts = self.find_contracts()
        self.readme = ""
        if (os.path.exists(self.context.cws() + "/README.md")):
            with open(self.context.cws() + "/README.md", "r") as f:
                self.readme = f.read()

    def analyze_contracts(self, project_summary):
        for contract in self.contracts:
            contract_list = extract_all_solidity_definitions(contract["content"])
            for contract_detail in contract_list:
                if (contract_detail["contract_name"] == "Unknown"):
                    print(f"Warning: Unknown contract name {json.dumps(contract_detail)}")
                    continue
                print("Analyzing " + json.dumps(contract_detail))
                prompt = f"""
                Analyze this smart contract.

                {json.dumps(contract_detail)}

                Can you summarize the contract: 
                1. Purpose of the contract based on functions and contract name
                2. Whether this contract is deployable based on whether the type of the contract is abstract / interface / library / concrete, and populate the is_deployable field
                """
                analyzer = ThreeStageAnalyzer(Contract)
                contract_summary = analyzer.ask_llm(prompt)
                contract_summary.type = contract_detail["type"]
                contract_summary.path = contract["path"]
                project_summary.add_contract(contract_summary)
        return project_summary

    def merge_project_summaries(self, project_from_readme, project_from_contracts):
        prompt = f"""
        Analyze the two project summaries and merge them into one. The first summary is created from readme file, so any contracts in this list will be incorrect.

        {json.dumps(project_from_readme.to_dict())}

        The second summary is created from the contracts, so it should be the main source of understanding.

        {json.dumps(project_from_contracts.to_dict())}

        Other considerations:
        1. Name of the project should be taken from the first summary.
        2. Second summary is accurate in terms of contracts and their purpose.
        3. Use a consistent format("None") for empty values for strings.

        """
        analyzer = ThreeStageAnalyzer(Project)
        summary = analyzer.ask_llm(json.dumps(project_from_readme.to_dict()) + "\n --------- \n" + json.dumps(project_from_contracts.to_dict()) + " \n Does the two summaries conflict each other? Can you merge them into one? Keep the contract list empty")
        return summary

    def get_prompt_for_refinement(self, existing_summary, user_prompt=None):
        return f"""
        Here is the existing project summary:
        {json.dumps(existing_summary.to_dict())}

        we need to refine this summary based on:
        1. Any new information from the contracts
        2. Additional user requirements below:

        {user_prompt if user_prompt else "None"}
        """

    def get_prompt_for_generation(self, user_prompt=None):
        base_prompt = f"""
        Analyze this smart contract project, dev_tool: {self.dev_tool}

        Provide a comprehensive summary including:
        1. Project purpose
        2. Main components
        3. Key functionality

        Do not add anything to the contract list yet.
        """
        if user_prompt:
            base_prompt += f"\n\nAdditional user requirements:\n{user_prompt}"
        return base_prompt

    def summarize(self, user_prompt=None):
        self.prepare()
        print("Analyzing the contracts")
        if self.summary_exists():
            existing_summary = self.load_summary()
            prompt = self.get_prompt_for_refinement(existing_summary, user_prompt)
            analyzer = ThreeStageAnalyzer(Project)
            project_summary = analyzer.ask_llm(prompt)
            self.project_summary = project_summary
            self.save()
            return self.project_summary
        project_from_readme = None
        base_prompt = self.get_prompt_for_generation(user_prompt)
        prompt = base_prompt
        if (self.readme != ""):
            prompt_with_readme = prompt + f"\n\n Project Readme:\n\n {self.readme}"
            # Add user prompt if provided
            analyzer = ThreeStageAnalyzer(Project)
            project_from_readme = analyzer.ask_llm(prompt_with_readme)
            project_from_readme.clear_contracts()
            print("Project summary from README")
            print(json.dumps(project_from_readme.to_dict()))
        contracts_summary = []
        project_from_contracts = None
        for contract in self.contracts:
            contracts_summary.append({
                "name": contract["name"]
            })
        prompt_with_contracts = prompt + f"\n\n Project Contracts:\n\n {json.dumps(contracts_summary)}"
        analyzer = ThreeStageAnalyzer(Project)
        project_from_contracts = analyzer.ask_llm(prompt_with_contracts)
        project_summary = project_from_contracts
        print("Project summary from contract names")
        print(json.dumps(project_summary.to_dict()))
        if (project_from_readme != None):
            project_summary = self.merge_project_summaries(project_from_readme, project_from_contracts)
        project_summary.clear_contracts()
        project_summary = self.analyze_contracts(project_summary)
        print("Analyzed all contracts")
        print(json.dumps(project_summary.to_dict()))
        self.project_summary = project_summary
        self.save()
        return self.project_summary
        #print("Analyzing " + contract["name"])

    def save(self):
        with open(self.context.summary_path(), 'w') as f:
            f.write(json.dumps(self.project_summary.to_dict()))
        self.context.commit("Updating project summary")

    def load_summary(self):
        if (os.path.exists(self.context.summary_path())):
            with open(self.context.summary_path(), "r") as f:
                content = json.loads(f.read())
                #print(json.dumps(content))
                return Project.load(content)
        return None
    
    def summary_exists(self):
        return os.path.exists(self.context.summary_path())
    

def __init__(context):
    """
    Initialize the summarizer with the given context.
    """
    return ProjectSummarizer(context)

