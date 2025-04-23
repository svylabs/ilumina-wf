#!/usr/bin/env python3
from .context import example_contexts
from .models import Project, Actors
from .openai import ask_openai
import json
import os
import sys

class ActorAnalyzer:
    
    def __init__(self, context, summary):
        self.context = context
        self.project_summary = summary
        self.actors = []

    def identify_actors(self, user_prompt=None):
        base_prompt = f"""
        Analyze this smart contract project:
        {json.dumps(self.project_summary.to_dict())}
        
        Identify:
        1. All market participants (actors) in the project
        2. Actions each actor can perform
        3. Probability of each action being executed
        """
        
        # Add user prompt if provided
        prompt = base_prompt
        if user_prompt:
            prompt = f"{base_prompt}\n\nAdditional user requirements:\n{user_prompt}"
        
        _, actors = ask_openai(prompt, Actors, task="reasoning")
        self.actors = actors
        return self.actors
        #print(json.dumps(self.actors.to_dict()))

    def prepare(self):
        pass

    def analyze(self, user_prompt=None):
        '''
        if (os.path.exists(self.context.actor_summary_path())):
            print("Actor summary exists")
            with open(self.context.actor_summary_path(), "r") as f:
                content = json.loads(f.read())
                self.actors = Actors.load(content)
                return self.actors
        print("Analyzing actors for the contracts")
        '''
        self.identify_actors(user_prompt=user_prompt)
        self.save()
        return self.actors

    def save(self):
        with open(self.context.actor_summary_path(), "w") as f:
            f.write(json.dumps(self.actors.to_dict()))
        self.context.commit("Updating actor summary")

    def load_summary(self):
        if (os.path.exists(self.context.actor_summary_path())):
            with open(self.context.actor_summary_path(), "r") as f:
                content = json.loads(f.read())
                #print(json.dumps(content))
                return Actors.load(content)
        return None
    
    def analysis_exists(self):
        return os.path.exists(self.context.summary_path())

if __name__ == "__main__":
    context_num = 0
    try:
        context_num = int(sys.argv[1])
    except:
        pass
    context = example_contexts[context_num]
    summary = Project.load_summary(context.summary_path())
    analyzer = ActorAnalyzer(context, summary)
    actors = analyzer.analyze()
    analyzer.save()
    print(json.dumps(actors.to_dict()))


