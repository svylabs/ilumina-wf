#!/usr/bin/env python3
import os
from openai import OpenAI
from pydantic import BaseModel
import json
from dotenv import load_dotenv
from lib.lib import Contract, Project
from lib.lib import extract_solidity_functions_and_contract_name
from lib.context import example_contexts
from lib.openai import ask_openai

MAX_TOKENS = 7600  # Adjust based on your model's limit
conversation = [
]

def count_tokens(messages):
    """Estimate token count based on message content length."""
    return sum(len(msg["content"]) for msg in messages)

""" def summarize_conversation(messages):
    Summarize long conversation to maintain context.
    summary_prompt = f"Can you summarize this content? {messages}"
    response = client.completions.create(model="chatgpt-4o-latest",
        prompt=summary_prompt)
    summary = response.choices[0].text.strip()
    return [{"role": "system", "content": "Conversation summary: " + summary}]
 """
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
            response = ask_openai(json.dumps(contract_detail) + " \n Can you summarize what this contract is about?", Contract, task="understand")
            contract_summary = response[1]
            project_summary.add_contract(contract_summary)
        return project_summary

    def merge_project_summaries(self, project_from_readme, project_from_contracts):
        response = ask_openai(json.dumps(project_from_readme.to_dict()) + "\n --------- \n" + json.dumps(project_from_contracts.to_dict()) + " \n Does the two summaries conflict each other? Can you merge them into one? Keep the contract list empty", Project, "understand")
        return response[1]

    def analyze(self):
        self.prepare()
        print("Analyzing the contracts")
        project_from_readme = None
        if (self.readme != ""):
            response = ask_openai(self.readme + " \n\n Can you summarize this above project? \n Keep the contract list empty in the return value", Project, task="understand")
            project_from_readme = response[1]
            print("Project summary from README")
            print(json.dumps(project_from_readme.to_dict()))
        contracts_summary = []
        project_from_contracts = None
        for contract in self.contracts:
            contracts_summary.append({
                "name": contract["name"]
            })
        response = ask_openai(json.dumps(contracts_summary) + " \n Can you summarize what the project could potentially be doing based on these contract names? Don't add anything to the contract list yet.", Project, task="understand")
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
        with open(self.context.cwd() + "/summary.json", "w") as f:
            f.write(json.dumps(self.project_summary.to_dict()))

    def load_summary(self):
        if (os.path.exists(self.context.summary_path())):
            with open(self.context.summary_path(), "r") as f:
                content = json.loads(f.read())
                #print(json.dumps(content))
                return Project.load(content)
        return None
    
    def analysis_exists(self):
        return os.path.exists(self.context.cws() + "/summary.json")


if __name__ == "__main__":
    context = example_contexts[0]
    analyzer = Analyzer(context)
    if not analyzer.analysis_exists():
        analyzer.analyze()
        analyzer.save()
    else:
        print("Analysis exists")
        summary = analyzer.load_summary()
        print(summary.contracts[0].summary)
        #print(summary.contracts[0].functions[].summary)
        #print(json.dumps(summary.contracts[0]))
        #print(json.dumps(summary.to_dict()))
        #print("Summary")


