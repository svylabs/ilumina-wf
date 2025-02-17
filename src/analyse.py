#!/usr/bin/env python3
import os
import openai
from pydantic import BaseModel
import json
from dotenv import load_dotenv

load_dotenv()

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
    
class Contract(BaseModel):
    path: str
    name: str
    type: str # external, library, interface
    summary: str
    functions: list[Function]

    def __str__(self):
        return json.dumps(self.dict())
    
class Project(BaseModel):
    name: str
    summary: str
    type: str
    dev_tool: str
    contracts: list[Contract]

    def __init__(self, name, ctx):
        self.name = name
        self.ctx = ctx
        self.contracts = []
    
    def __str__(self):
        return json.dumps(self.dict())

openai.api_key = os.getenv("OPENAI_API_KEY")

MAX_TOKENS = 7600  # Adjust based on your model's limit
conversation = [
]

def count_tokens(messages):
    """Estimate token count based on message content length."""
    return sum(len(msg["content"]) for msg in messages)

def summarize_conversation(messages):
    """Summarize long conversation to maintain context."""
    summary_prompt = f"Summarize the following conversation:\n{messages}"
    response = openai.Completion.create(
        engine="davinci",
        prompt=summary_prompt,
        max_tokens=MAX_TOKENS
    )
    summary = response['choices'][0]['text'].strip()
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
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=conversation,
            response_format=Contract
        )
        contract = response['choices'][0]['message'].parsed
        conversation.append({"role": "assistant", "content": contract})
        return (type, contract)
    elif type == "project":
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=conversation,
            response_format=Project
        )
        project = response['choices'][0]['message'].parsed
        conversation.append({"role": "assistant", "content": project})
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
            response = ask_openai(json.dumps(contract["content"]) + " \n Can you summarize what this contract is about?", "contract")
            contract_summary = response[1]
            project_summary.contracts.append(contract_summary)
        return project_summary

    def merge_project_summaries(self, project_from_readme, project_from_contracts):
        response = ask_openai(json.dumps(project_from_readme) + " --------- " + json.dumps(project_from_contracts) + " \n Does the two summaries conflict each other? Can you merge them into one? Don't add anything to the contract list yet.", "project")
        return response[1]
    
    def analyze(self):
        self.prepare()
        print("Analyzing the contracts")
        project_from_readme = None
        if (self.readme != ""):
            response = ask_openai(self.readme + " \n Can you summarize what this project is about? Don't add anything to the contract list yet", "project")
            project_from_readme = response[1]
            print("Project summary from README")
            print(json.dumps(project_from_readme))
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
        print(json.dumps(project_summary))
        if (project_from_readme != None):
            project_summary = self.merge_project_summaries(project_from_readme, project_from_contracts)
        project_summary = self.analyze_contracts(project_summary)
        print(json.dumps(project_summary))
        print("Analyzing " + contract["name"])


if __name__ == "__main__":
    context = RunContext("1", "https://github.com/svylabs/predify", "/tmp/workspaces")
    analyzer = Analyzer(context)
    analyzer.analyze()

