import os
from .models import Project, Contract
from .openai import ask_openai

class ProjectSummarizer:
    def __init__(self, context):
        self.context = context
        self.project_summary = None

    def find_dev_tool(self):
        if os.path.exists("/tmp/workspace/hardhat.config.js"):
            return "hardhat"
        elif os.path.exists("/tmp/workspace/foundry.toml"):
            return "foundry"
        return "unknown"

    def summarize(self):
        if self.context.gcs.file_exists(self.context.summary_path()):
            content = self.context.gcs.read_json(self.context.summary_path())
            self.project_summary = Project(**content)
            return
        
        dev_tool = self.find_dev_tool()
        prompt = f"""
        Analyze this smart contract project (dev tool: {dev_tool}).
        Provide a comprehensive summary including:
        1. Project purpose
        2. Main components
        3. Key functionality
        """
        _, summary = ask_openai(prompt, Project)
        self.project_summary = summary
        self.project_summary.dev_tool = dev_tool
        
        self.context.gcs.write_json(
            self.context.summary_path(),
            self.project_summary.to_dict()
        )