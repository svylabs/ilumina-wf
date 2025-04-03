from pydantic import BaseModel
from .openai import ask_openai
import json

class Action(BaseModel):
    name: str
    summary: str
    contract_name: str
    function_name: str
    probability: float

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

    def to_dict(self):
        return {
            "name": self.name,
            "summary": self.summary,
            "actions": [action.to_dict() for action in self.actions]
        }

class Actors(BaseModel):
    actors: list[Actor]

    def to_dict(self):
        return {
            "actors": [actor.to_dict() for actor in self.actors]
        }

class ActorAnalyzer:
    def __init__(self, context, project_summary):
        self.context = context
        self.project_summary = project_summary
        self.actors = None

    def identify_actors(self, user_prompt=None):
        base_prompt = f"""
        Analyze this smart contract project:
        {json.dumps(self.project_summary.to_dict())}
        
        Identify:
        1. All actor roles (users, contracts, external services)
        2. Actions each actor can perform
        3. Probability of each action being executed
        """
        
        # Add user prompt if provided
        prompt = base_prompt
        if user_prompt:
            prompt = f"{base_prompt}\n\nAdditional user requirements:\n{user_prompt}"
        
        _, actors = ask_openai(prompt, Actors, task="reasoning")
        self.actors = actors

    def analyze(self, user_prompt=None):
        if not user_prompt and self.context.gcs.file_exists(self.context.actor_summary_path()):
            content = self.context.gcs.read_json(self.context.actor_summary_path())
            return Actors(**content)
        
        self.identify_actors(user_prompt)
        self.context.gcs.write_json(
            self.context.actor_summary_path(),
            self.actors.to_dict()
        )
        return self.actors