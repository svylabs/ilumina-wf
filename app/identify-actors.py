#!/usr/bin/env python3
from .context import RunContext, example_contexts
from .lib import Project
from .openai import ask_openai
import json
import os
from pydantic import BaseModel
import sys

class Action(BaseModel):
    name: str
    summary: str
    contract_name: str
    function_name: str
    probability: float
    #actors: list[Actor]

    def to_dict(self):
        return {
            "name": self.name,
            "summary": self.summary,
            "contract_name": self.contract_name,
            "function_name": self.function_name,
            "probability": self.probability
        }
    

class Actor(BaseModel):
    name: str
    summary: str
    actions: list[Action]

    @classmethod
    def load(cls, data):
        return cls(**data)

    def to_dict(self):
        return {
            "name": self.name,
            "summary": self.summary,
            "actions": [action.to_dict() for action in self.actions]
        }

class UserJourney(BaseModel):
    name: str
    summary: str
    actions: list[Action]

    @classmethod
    def load(cls, data):
        return cls(**data)
    
    def to_dict(self):
        return {
            "name": self.name,
            "summary": self.summary,
            "actions": [action.to_dict() for action in self.actions]
        }
    
class UserJourneys(BaseModel):
    user_journeys: list[UserJourney]

    @classmethod
    def load(cls, data):
        return cls(**data)

    def to_dict(self):
        return {
            "user_journeys": [user_journey.to_dict() for user_journey in self.user_journeys]
        }
    
class Actions(BaseModel):
    actions: list[Action]

    @classmethod
    def load(cls, data):
        return cls(**data)

    def to_dict(self):
        return {
            "actions": [action.to_dict() for action in self.actions]
        }
    
class Actors(BaseModel):
    actors: list[Actor]

    @classmethod
    def load(cls, data):
        return cls(**data)

    def to_dict(self):
        return {
            "actors": [actor.to_dict() for actor in self.actors]
        }

class ActorAnalyzer:
    
    def __init__(self, context, summary):
        self.context = context
        self.project_summary = summary
        self.actors = []

    def identify_actors(self):
        response = ask_openai("The following is the json description of the smart contract project.\n"  
                                         + json.dumps(self.project_summary.to_dict()) 
                                         + " \n\n " 
                                         + """Can you identify the list of market participants in this project?
                                            Identify actions that each of the market participant can take.
                                         """, 
                                Actors, task="reasoning")
        self.actors = response[1]
        #print(json.dumps(self.actors.to_dict()))

    def prepare(self):
        pass

    def analyze(self):
        self.prepare()
        self.identify_actors()
        print("Analyzing actors for the contracts")
        return self.actors

    def save(self):
        with open(self.context.actor_summary_path(), "w") as f:
            f.write(json.dumps(self.actors.to_dict()))

    def load_summary(self):
        if (os.path.exists(self.context.actor_summary_path())):
            with open(self.context.actor_summary_path(), "r") as f:
                content = json.loads(f.read())
                #print(json.dumps(content))
                return Actor.load(content)
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


