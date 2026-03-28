class ActionValidationCodeGenerator(BaseCodeGenerator):
    def generate_code(self, action: Action, validation: ActionValidation) -> str:
        prompt = f"""
        Generate the code for the following action validation:

        Action: {action.name}
        Validation Requirements: {validation.requirements}

        The code should be in Python and use the unittest framework.
        """ 
        code = SimpleCodeGenerator(system_prompt="You are an expert Python developer specializing in writing unit tests for smart contract actions.").ask_llm(prompt)
        return code