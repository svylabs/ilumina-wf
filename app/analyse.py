#!/usr/bin/env python3
import json
from .context import example_contexts
from .openai import ask_openai
import sys
from .actor import ActorAnalyzer
from .download import Downloader
from .summarizer import ProjectSummarizer
from .models import Project, DeploymentInstruction
from .deployment import DeploymentAnalyzer

class Analyzer:
    def __init__(self, context):
        self.context = context
        self.current_step = None

    def not_done(self):
        if self.current_step != "done":
            return True
        return False
    
    def download(self):
        downloader = Downloader(self.context)
        downloader.download()

    def summarize(self, user_prompt=None):
        summarizer = ProjectSummarizer(self.context)
        return summarizer.summarize(user_prompt=user_prompt)

    def identify_actors(self, user_prompt=None):
        project_summary = None
        with open(self.context.summary_path(), 'r') as f:
            project_summary = Project.load(json.loads(f.read()))
        actor_analyzer = ActorAnalyzer(self.context, project_summary)
        return actor_analyzer.analyze(user_prompt=user_prompt)
    
    def step(self):
        print("Running step " + str(self.current_step))
        if self.current_step == None:
            self.current_step = "download"
            self.download()
        elif self.current_step == "download":
            self.current_step = "summarize"
            self.summarize()
        elif self.current_step == "summarize":
            self.current_step = "actor_analysis"
            self.identify_actors()
        elif self.current_step == "actor_analysis":
            self.current_step = "done"

    def save(self):
        # Save the step in DB
        print("Saving step " + str(self.current_step))
        if self.current_step == "download":
            pass
        elif self.current_step == "summarize":
            pass
        elif self.current_step == "actor_analysis":
            pass

    def print_current_step(self):
        if self.current_step == None:
            print("Run not started")
        elif self.current_step == "download":
            print("Downloaded the project in " + self.context.cws())
        elif self.current_step == "summarize":
            with open(self.context.summary_path(), 'r') as f:
                print("Project summary:")
                print(f.read())
        elif self.current_step == "actor_analysis":
            with open(self.context.actor_summary_path(), 'r') as f:
                print("Actor summary:")
                print(f.read())
        elif self.current_step == "done":
            print("Analysis complete")

    def generate_deployment_instructions(self, user_prompt=None):
        deployment_analyzer = DeploymentAnalyzer(self.context)
        contracts = deployment_analyzer.analyze(user_prompt=user_prompt)

        # Prepare deployment sequence
        sequence = DeploymentInstruction.prepare_sequence(contracts)

        # Prompt user for missing parameter values
        for step in sequence:
            for param in step.get("Params", []):
                if param["value"] is None:
                    param["value"] = input(f"Enter value for {param['name']} in {step['Type']} step: ")

        # Create DeploymentInstruction object
        deployment_instruction = DeploymentInstruction(sequence=sequence)
        print(json.dumps(deployment_instruction.to_dict(), indent=2))
        return deployment_instruction


if __name__ == "__main__":
    context_num = 0
    try:
        context_num = int(sys.argv[1])
    except:
        pass
    context = example_contexts[context_num]
    analyzer = Analyzer(context)
    while analyzer.not_done():
        analyzer.step()
        analyzer.print_current_step()


