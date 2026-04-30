from .context import RunContext
from .three_stage_llm_call import ThreeStageAnalyzer

class ActionPseudocodeGenerator:
    def __init__(self, action, context: RunContext):
        self.action = action


    def _generate_prompt(self, action_summary):
        """
        Generate a prompt for the LLM to create pseudocode for the action.
        """
        return f"""
        You are an expert in generating pseudocode for smart contract action.
        
        Action Name: {self.action.name}
        Description: {self.action.description}

        Action Summary: {action_summary}
        
        Please generate pseudocode that accurately represents the logic and flow for this action.
        """

    def generate_pseudocode(self):
        """
        Generate pseudocode for the action using the ThreeStageAnalyzer.
        """
        analyzer = ThreeStageAnalyzer(
            self.action,
            system_prompt="You are an expert in generating pseudocode for smart contract actions."
        )
        
        prompt = f"Generate pseudocode for the action: {self.action.name} with description: {self.action.description}"
        
        pseudocode = analyzer.ask_llm(prompt)
        
        return pseudocode
    

        