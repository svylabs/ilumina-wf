#!/usr/bin/env python3
from .context import example_contexts
from .models import Project, Actors
from .openai import ask_openai
import json
import os
import sys
from .three_stage_llm_call import ThreeStageAnalyzer

class ActorAnalyzer:
    
    def __init__(self, context, summary):
        self.context = context
        self.project_summary = summary
        self.actors = []

    def get_prompt_for_refinement(self, project_summary, existing_actors, user_prompt=None):
        return f"""
        Here is the project summary:
        {json.dumps(project_summary.to_dict())}

        Here are the existing actor definitions:
        {json.dumps(existing_actors.to_dict())}

        We need to refine the actor definitions based on:
        1. Any changes in the project summary
        2. Additional user requirements below:
        
        {user_prompt if user_prompt else "None"}
        """

    def get_prompt_for_generating_actors(self, project_summary, user_prompt=None):
        return f"""
        Analyze this smart contract project:
        {json.dumps(project_summary.to_dict())}
        
        Identify:
        1. All market participants (actors) in the project
        2. Actions each actor can perform
        3. Probability of each action being executed

        Additional user requirements:
        {user_prompt if user_prompt else "None"}
        """

    def identify_actors(self, user_prompt=None):
        existing_actors = None
        refine = False
        if os.path.exists(self.context.actor_summary_path()):
            with open(self.context.actor_summary_path(), "r") as f:
                content = json.loads(f.read())
                existing_actors = Actors.load(content)
                refine = True

        if refine:
            prompt = self.get_prompt_for_refinement(
                project_summary=self.project_summary,
                existing_actors=existing_actors,
                user_prompt=user_prompt
            )
        else:
            prompt = self.get_prompt_for_generating_actors(
                project_summary=self.project_summary,
                user_prompt=user_prompt
            )

        analyzer = ThreeStageAnalyzer(Actors)
        actors = analyzer.ask_llm(prompt)
        self.actors = actors
        return self.actors
        #print(json.dumps(self.actors.to_dict()))

    def prepare(self):
        pass

    def analyze(self, user_prompt=None):
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


