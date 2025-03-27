#!/usr/bin/env python3
import json
from .context import example_contexts
from .openai import ask_openai
import sys
from .actor import ActorAnalyzer
from .download import Downloader
from .summarizer import ProjectSummarizer
from .models import Project

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
        self.current_step = None

    def not_done(self):
        if self.current_step != "done":
            return True
        return False
    
    def download(self):
        downloader = Downloader(self.context)
        downloader.download()

    def summarize(self):
        summarizer = ProjectSummarizer(self.context)
        summarizer.summarize()

    def identify_actors(self):
        project_summary = None
        with open(self.context.summary_path(), 'r') as f:
            project_summary = Project.load(json.loads(f.read()))
        actor_analyzer = ActorAnalyzer(self.context, project_summary)
        actor_analyzer.analyze()
    
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


