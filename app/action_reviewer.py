from app.models import ActionReview
from app.three_stage_llm_call import ThreeStageAnalyzer
import os
import json
import re

class ActionReviewer:
    def __init__(self, context):
        self.context = context

    def review_action(self, contract_name, function_name):
        """Review and validate an action implementation against its validation rules and code"""
        # Load actors summary
        actors = self.context.actor_summary()
        if not actors:
            raise ValueError("Actors summary not found")
        
        action = actors.find_action(contract_name, function_name)
        if not action:
            raise ValueError(f"Action {function_name} for contract {contract_name} not found")

        # Load action implementation and summary
        action_summary = self._load_action_summary(action)
        action_code = self._load_action_code(action)
        contract_code = self._load_contract_code(contract_name)

        # Prepare review prompt
        review_prompt = self._build_review_prompt(
            contract_name, 
            function_name,
            action_summary,
            contract_code,
            action_code
        )

        # Create analyzer and get review results
        analyzer = ThreeStageAnalyzer(ActionReview)
        return analyzer.ask_llm(review_prompt, guidelines=[
            "1. Be thorough in checking all validation rules",
            "2. Verify all state changes are properly validated",
            "3. Check parameter generation follows the rules",
            "4. Look for any potential security issues",
            "5. Provide specific, actionable feedback"
        ])

    def _load_action_summary(self, action):
        """Load action summary from file"""
        action_summary_path = self.context.action_summary_path(action)
        if not os.path.exists(action_summary_path):
            raise FileNotFoundError("Action analysis not found")
        
        with open(action_summary_path, 'r') as f:
            return json.load(f)

    def _load_action_code(self, action):
        """Load action implementation code"""
        action_code_path = self.context.action_code_path(action)
        if not os.path.exists(action_code_path):
            raise FileNotFoundError("Action implementation not found")
        
        with open(action_code_path, 'r') as f:
            return f.read()

    def _load_contract_code(self, contract_name):
        """Load contract code from workspace"""
        contract_path = os.path.join(self.context.cws(), f"{contract_name}.sol")
        if os.path.exists(contract_path):
            with open(contract_path, "r") as f:
                return f.read()
        
        # Search for contract in other files if not found in direct path
        for root, _, files in os.walk(self.context.cws()):
            for file in files:
                if file.endswith(".sol"):
                    with open(os.path.join(root, file), "r") as f:
                        content = f.read()
                        if f"contract {contract_name}" in content:
                            return content
        
        raise FileNotFoundError(f"Contract {contract_name} not found in workspace")

    def _build_review_prompt(self, contract_name, function_name, action_summary, contract_code, action_code):
        """Build the LLM review prompt"""
        return f"""
Review the action implementation for {contract_name}.{function_name} and validate it against:
1. The expected state changes and validation rules
2. The actual contract implementation
3. The generated action code

Action Summary:
{json.dumps(action_summary, indent=2)}

Contract Code:
{contract_code}

Action Implementation:
{action_code}

Please review and provide:
1. Any mismatches between the validation rules and implementation
2. Any missing validations
3. Any incorrect parameter generation
4. Any potential issues with the action code
5. Suggestions for improvement
"""