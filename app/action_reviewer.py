import os
import json
from typing import Optional
from .models import ActionReview, Review
from .context import RunContext
from .three_stage_llm_call import ThreeStageAnalyzer
from .models import Action

class ActionReviewer:
    def __init__(self, context: RunContext):
        self.context = context
        # Create reviews directory if it doesn't exist
        self.reviews_dir = os.path.join(
            context.simulation_path(), 
            "reviews", 
            "actions"
        )
        os.makedirs(self.reviews_dir, exist_ok=True)

    def review_action(
        self, 
        contract_name: str, 
        function_name: str
    ) -> ActionReview:
        """
        Conduct a thorough code review of an action implementation.
        
        Args:
            contract_name: Name of the contract
            function_name: Name of the function being reviewed
            
        Returns:
            ActionReview containing all findings
        """
        try:
            print(f"Starting review for {contract_name}.{function_name}")

            # Load all required components
            action = self._get_action(contract_name, function_name)
            print("1. Action loaded successfully")

            action_summary = self._load_action_summary(action)
            print("2. Action summary loaded")

            action_code = self._load_action_code(action)
            print("3. Action code loaded")

            contract_code = self._load_contract_code(contract_name)
            print("4. Contract code loaded")

            # Prepare the review
            numbered_code = self._number_code_lines(action_code)
            print("5. Code lines numbered")

            review_prompt = self._create_review_prompt(
                contract_name,
                function_name,
                action_summary,
                contract_code,
                numbered_code
            )
            print("6. Review prompt created")
            print(f"review_prompt:\n{review_prompt}\n")

            # Get the review from LLM
            analyzer = ThreeStageAnalyzer(ActionReview)
            print("7. Analyzer initialized")

            review = analyzer.ask_llm(review_prompt, guidelines=[
                "Be specific about line numbers",
                "Categorize issues precisely",
                "Provide concrete suggestions",
                "Avoid vague language"
            ])
            print("8. LLM analysis completed")

            # Validate the review before saving
            if not isinstance(review, ActionReview):
                raise ValueError("LLM returned invalid review format")
            print("9. Review validated")

            # Save the review
            self._save_review_file(contract_name, function_name, review)
            print("10. Review saved successfully")
            
            return review

        except Exception as e:
            raise Exception(f"Action review failed: {str(e)}")

    def _get_action(self, contract_name: str, function_name: str) -> Action:
        """Retrieve the action definition"""
        actors = self.context.actor_summary()
        if not actors:
            raise ValueError("No actors summary available")
        action = actors.find_action(contract_name, function_name)
        if not action:
            raise ValueError(f"Action {contract_name}.{function_name} not found")
        return action

    def _load_action_summary(self, action: Action) -> dict:
        """Load the action analysis summary"""
        summary_path = self.context.action_summary_path(action)
        if not os.path.exists(summary_path):
            raise FileNotFoundError(f"Action summary not found at {summary_path}")
        with open(summary_path, 'r') as f:
            return json.load(f)

    def _load_action_code(self, action: Action) -> str:
        """Load the action implementation code"""
        code_path = self.context.action_code_path(action)
        if not os.path.exists(code_path):
            raise FileNotFoundError(f"Action code not found at {code_path}")
        with open(code_path, 'r') as f:
            return f.read()

    def _load_contract_code(self, contract_name: str) -> str:
        """Load the original contract code"""
        contract_path = os.path.join(self.context.cws(), f"{contract_name}.sol")
        if os.path.exists(contract_path):
            with open(contract_path, "r") as f:
                return f.read()
        
        # Search through all .sol files if not found directly
        for root, _, files in os.walk(self.context.cws()):
            for file in files:
                if file.endswith(".sol"):
                    with open(os.path.join(root, file), "r") as f:
                        content = f.read()
                        if f"contract {contract_name}" in content:
                            return content
        
        raise FileNotFoundError(f"Contract {contract_name} not found")

    def _number_code_lines(self, code: str) -> str:
        """Add line numbers to code for precise referencing"""
        lines = code.split('\n')
        return '\n'.join(f"{i+1}: {line}" for i, line in enumerate(lines))

    def _create_review_prompt(
        self,
        contract_name: str,
        function_name: str,
        action_summary: dict,
        contract_code: str,
        numbered_action_code: str
    ) -> str:
        """Create the detailed review prompt for LLM"""
        return f"""
Conduct a code review for {contract_name}.{function_name} action implementation.

Requirements:
1. Identify missing validations (should exist but don't)
2. Find errors in existing validations
3. Check parameter generation logic
4. Analyze execution flow

For each issue:
- Specify exact line number
- Categorize (validation|parameter|logic)
- Describe clearly
- Suggest concrete fix

Action Summary:
{json.dumps(action_summary, indent=2)}

Original Contract:
{contract_code}

Action Implementation (with line numbers):
{numbered_action_code}
"""

    def _save_review_file(
        self,
        contract_name: str,
        function_name: str,
        review: ActionReview
    ) -> None:
        """Save the review to a JSON file"""
        filename = f"{contract_name}_{function_name}_review.json"
        filepath = os.path.join(self.reviews_dir, filename)
        
        with open(filepath, 'w') as f:
            json.dump(review.to_dict(), f, indent=2)