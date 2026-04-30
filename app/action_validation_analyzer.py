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


    def get_prompt_for_refining(self, actor, action, actors, user_prompt="", refine=False):
        prompt = f"""
        """
        return prompt
    
    def analysis_exists(self, action: Action):
        summary_path = self.context.action_validation_summary_path(action)
        return os.path.exists(summary_path)
    

    def prompt_for_refinement(self, actor, action, actors, user_prompt=""):
        prompt = f"""
        You have already created a smoke test plan for the action: {action.name} by the actor: {actor.name}.
        Now, please refine the smoke test plan based on the following additional requirements from the user:
        {user_prompt}

        Here is the previous smoke test plan:
        {json.dumps(self.analyze(actor, action, actors), indent=2)}

        Here is the summary of all actors and their actions.
        {json.dumps(actors.to_dict(), indent=2)}

        Please provide the refined smoke test plan.
        """
        return prompt

    def analyze(self, actor, action, actors, user_prompt="", refine=False):
        if self.analysis_exists(action) and not refine:
            summary_path = self.context.action_validation_summary_path(action)
            with open(summary_path, "r") as f:
                data = json.load(f)
                return ActionValidation.from_dict(data)
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
        2. User index field should be numbered starting from 1, and incremented for each new user needed in the sequence. Some steps may be performed by the same user.

        Additional Requirements from the user:
        {user_prompt}

        """
        if refine:
            prompt = self.prompt_for_refinement(actor, action, actors, user_prompt)
        validation_sequence = ThreeStageAnalyzer(ActionValidation, system_prompt="You are an expert in analyzing smart contract actions and creating smoke test plans.", plan=self.context.plan).ask_llm(prompt)
        self.save_analysis(action, validation_sequence)
        return validation_sequence
    
    def save_analysis(self, action: Action, analysis: ActionValidation):
        summary_path = self.context.action_validation_summary_path(action)
        with open(summary_path, "w") as f:
            json.dump(analysis.to_dict(), f, indent=2)

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