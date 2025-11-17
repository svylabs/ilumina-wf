#action_validation_analyzer.py
import os
import dotenv
dotenv.load_dotenv()
    
import tempfile
import subprocess
import json
from .three_stage_llm_call import ThreeStageAnalyzer
from .models import Action, ActionValidation

class ActionValidationAnalyzer:
    def __init__(self, context):
        self.context = context

    def analyze(self, actor, action, actors):
        '''
        Analyze the action validation logic for the given action in the contract.
        '''
        prompt = f"""
        You are an expert in understanding smart contract actions and create a smoke test plan for validating the actions.

        An action is a self contained client side atomic operation - that can generate required parameters, call the smart contract function, and validate the state changes made by the smart contract function.
        
        Here is the summary of all actors and their actions.
        {json.dumps(actors.to_dict(), indent=2)}

        and you are analysing the action by the actor: {actor.name} and the action is: {action.name}

        Please provide the sequence of steps(from among the list of actions above) to perform a smoke test of this particular action. One action may be dependent on other actions or there could be no dependency in the base case.
        1. Calling correct actions to set up state prior to executing the action being tested ({action.name})
        2. Calling the action that is being tested ({action.name})
        3. Assume that executions of each action already validates state changes of that action. So no extra steps are needed to validate state changes made by an action.

        Note:
        1. The smoke test sequence must be self contained, meaning it must not assume any prior state or actions outside of the sequence. So any state changes (eg: oracle updates) must be in the sequence of steps.

        """
        validation_sequence = ThreeStageAnalyzer(ActionValidation, system_prompt="You are an expert in analyzing smart contract actions and creating smoke test plans.", plan=self.context.plan).ask_llm(prompt)
        return validation_sequence

if __name__ == "__main__":
    from app.context import prepare_context
    context = prepare_context({
        "run_id": "1747743579",
        "submission_id": "b2467fc4-e77a-4529-bcea-09c31cb2e8fe",
        "github_repository_url": "https://github.com/svylabs/stablebase",
        "plan": "paid"
    }, needs_parallel_workspace=False)
    analyzer = ActionValidationAnalyzer(context)
    actors = context.actor_summary()
    result = analyzer.analyze(actors.actors[0], actors.actors[0].actions[6], actors)
    print(json.dumps(result.to_dict(), indent=2))     