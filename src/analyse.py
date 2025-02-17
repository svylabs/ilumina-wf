#!/usr/bin/env python3
import os
from openai import OpenAI
from pydantic import BaseModel
import json
from dotenv import load_dotenv
import re

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
import re

def extract_solidity_functions_and_contract_name(content):
    """Extract the contract name and public/external functions from a Solidity contract file."""
    #with open(file_path, 'r') as f:
    #    content = f.read()

    # Extract contract name
    contract_name_pattern = r'\b(contract|interface|library)\s+(\w+)'
    contract_match = re.search(contract_name_pattern, content)
    contract_name = contract_match.group(2) if contract_match else "Unknown"

    # Updated regex to capture public/external function definitions across multiple lines
    function_pattern = r'function\s+(\w+)\s*\(([^)]*)\)\s*(?:public|external)\s*(?:view|pure|payable)?\s*(?:returns\s*\(([^)]*)\))?'
    matches = re.findall(function_pattern, content, re.DOTALL)

    functions = []
    for match in matches:
        function_name, params, returns = match
        param_list = [param.strip() for param in params.split(',')] if params else []
        visibility = "public" if "public" in content or "external" in content else "unknown"
        returns = returns.strip() if returns else None

        functions.append({
            "function_name": function_name,
            "parameters": param_list,
            "visibility": visibility,
            "returns": returns
        })

    return {"contract_name": contract_name, "functions": functions}

class RunContext:
    def __init__(self, run_id, repo, workspace):
        self.run_id = run_id
        self.repo = repo
        self.workspace = workspace
        self.name = repo.split("/")[-1]

    def get_run_id(self):
        return self.run_id

    def cwd(self):
        return self.workspace + "/" + self.run_id

    def cws(self):
        return self.cwd() + "/" + self.name

class Function(BaseModel):
    name: str
    summary: str
    inputs: list[str]
    outputs: list[str]

    def __str__(self):
        return json.dumps(self.dict())
    

    def to_dict(self):
        return {
            "name": self.name,
            "summary": self.summary,
            "inputs": self.inputs,
            "outputs": self.outputs
        }

class Contract(BaseModel):
    path: str
    name: str
    type: str # external, library, interface
    summary: str
    functions: list[Function]

    def __str__(self):
        return json.dumps(self.dict())
    
    def to_dict(self):
        return {
            "path": self.path,
            "name": self.name,
            "type": self.type,
            "summary": self.summary,
            "functions": [function.to_dict() for function in self.functions]
        }

class Project(BaseModel):
    name: str
    summary: str
    type: str
    dev_tool: str
    contracts: list[Contract]

    def __str__(self):
        return json.dumps(self.dict())
    
    def to_dict(self):
        return {
            "name": self.name,
            "summary": self.summary,
            "type": self.type,
            "dev_tool": self.dev_tool,
            "contracts": [contract.to_dict() for contract in self.contracts]
        }
    
    def clear_contracts(self):
        self.contracts = []

    def add_contract(self, contract):
        self.contracts.append(contract)

    @classmethod
    def load(cls, data):
        return cls(**data)


MAX_TOKENS = 7600  # Adjust based on your model's limit
conversation = [
]

def count_tokens(messages):
    """Estimate token count based on message content length."""
    return sum(len(msg["content"]) for msg in messages)

def summarize_conversation(messages):
    """Summarize long conversation to maintain context."""
    summary_prompt = f"Summarize the following conversation:\n{messages}"
    response = client.completions.create(model="davinci-002",
        prompt=summary_prompt,
        max_tokens=MAX_TOKENS)
    summary = response.choices[0].text.strip()
    return [{"role": "system", "content": "Conversation summary: " + summary}]

def ask_openai(user_input, type, conversation=conversation):
    # Add user message
    conversation.append({"role": "user", "content": user_input})

    # Check token limit
    if count_tokens(conversation) > MAX_TOKENS:
        print("🧠 Summarizing conversation...")
        summary = summarize_conversation(conversation)
        # Reset with summary only
        conversation.clear()
        conversation.extend(summary)

    # Get response
    if type == "contract":
        response = client.beta.chat.completions.parse(model="gpt-4o",
            messages=conversation,
            response_format=Contract)
        #print(response)
        contract = response.choices[0].message.parsed
        #conversation.append({"role": "assistant", "content": contract})
        return (type, contract)
    elif type == "project":
        response = client.beta.chat.completions.parse(model="gpt-4o",
            messages=conversation,
            response_format=Project)
        #print(response)
        project = response.choices[0].message.parsed
        #conversation.append({"role": "assistant", "content": project})
        return (type, project)


class Analyzer:
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
            contract_detail = extract_solidity_functions_and_contract_name(contract["content"])
            print("Analyzing " + json.dumps(contract_detail))
            response = ask_openai(json.dumps(contract_detail) + " \n Can you summarize what this contract is about?", "contract")
            contract_summary = response[1]
            project_summary.add_contract(contract_summary)
        return project_summary

    def merge_project_summaries(self, project_from_readme, project_from_contracts):
        response = ask_openai(json.dumps(project_from_readme.to_dict()) + " --------- " + json.dumps(project_from_contracts.to_dict()) + " \n Does the two summaries conflict each other? Can you merge them into one? Keep the contract list empty", "project")
        return response[1]

    def analyze(self):
        self.prepare()
        print("Analyzing the contracts")
        project_from_readme = None
        if (self.readme != ""):
            response = ask_openai(self.readme + " \n\n Can you summarize what this project is about? Keep the contract list empty.", "project")
            project_from_readme = response[1]
            print("Project summary from README")
            print(json.dumps(project_from_readme.to_dict()))
        contracts_summary = []
        project_from_contracts = None
        for contract in self.contracts:
            contracts_summary.append({
                "name": contract["name"]
            })
        response = ask_openai(json.dumps(contracts_summary) + " \n Can you summarize what the project could potentially be doing based on these contract names? Don't add anything to the contract list yet.", "project")
        project_from_contracts = response[1]
        project_summary = project_from_contracts
        print("Project summary from contract names")
        print(json.dumps(project_summary.to_dict()))
        if (project_from_readme != None):
            project_summary = self.merge_project_summaries(project_from_readme, project_from_contracts)
        project_summary.clear_contracts()
        project_summary = self.analyze_contracts(project_summary)
        print(json.dumps(project_summary.to_dict()))
        self.project_summary = project_summary
        #print("Analyzing " + contract["name"])

    def save(self):
        with open(self.context.cws() + "/summary.json", "w") as f:
            f.write(json.dumps(self.project_summary.to_dict()))

    def load_summary(self):
        if (os.path.exists(self.context.cws() + "/summary.json")):
            with open(self.context.cws() + "/summary.json", "r") as f:
                content = json.loads(f.read())
                #print(json.dumps(content))
                return Project.load(content)
        return None
    
    def analysis_exists(self):
        return os.path.exists(self.context.cws() + "/summary.json")

    


if __name__ == "__main__":
    context = RunContext("1", "https://github.com/svylabs/predify", "/tmp/workspaces")
    analyzer = Analyzer(context)
    if not analyzer.analysis_exists():
        analyzer.analyze()
        analyzer.save()
    else:
        print("Analysis exists")
        summary = analyzer.load_summary()
        print(summary.contracts[0].summary)
        #print(json.dumps(summary.contracts[0]))
        #print(json.dumps(summary.to_dict()))
        #print("Summary")


