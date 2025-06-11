# implement_review_comments.py
import os
import json
from app.context import prepare_context
from app.models import ActionReview, Review, Code
from app.three_stage_llm_call import ThreeStageAnalyzer
from typing import List, Dict, Optional

def implement_review_comments(submission, contract_name: str, function_name: str, update_status_fn=None) -> Dict:
    try:
        context = prepare_context(submission, optimize=False, needs_parallel_workspace=False)
        
        # Path setup
        reviews_dir = os.path.join(context.simulation_path(), "reviews", "actions")
        review_file = os.path.join(reviews_dir, f"{contract_name}_{function_name}_review.json")
        code_file = os.path.join(context.simulation_path(), "simulation", "actions", 
                               f"{contract_name}_{function_name}.ts")
        
        # Validate files exist
        if not os.path.exists(review_file):
            return {"status": "error", "message": f"Review file not found: {review_file}"}
        if not os.path.exists(code_file):
            return {"status": "error", "message": f"Action code file not found: {code_file}"}

        # Load review and code
        with open(review_file, "r") as f:
            review_data = json.load(f)
            review = ActionReview(**review_data)
        
        with open(code_file, "r") as f:
            original_code = f.read()
        
        # System prompt for the LLM
        system_prompt = """You are an expert smart contract developer and TypeScript programmer. 
        Your task is to implement fixes for code review comments in a precise and maintainable way.
        
        Guidelines:
        1. Preserve the original functionality while fixing issues
        2. Add clear comments explaining the changes
        3. Follow the project's coding style
        4. Ensure type safety and proper error handling
        5. Make minimal necessary changes
        6. Return the complete updated code with your changes implemented"""

        implemented_changes = []
        current_code = original_code
        
        # Process missing validations
        for validation in review.missing_validations:
            user_prompt = f"""
            Add missing validation for: {validation}
            
            Original code:
            {current_code}
            
            Requirements:
            1. Add the validation logic
            2. Include appropriate error handling
            3. Add comments explaining the validation
            4. Return the complete updated code
            """
            # Initialize ThreeStageAnalyzer
            analyzer = ThreeStageAnalyzer(Code, system_prompt=system_prompt)

            # Get the fix from LLM
            fixed_code = analyzer.ask_llm(
                prompt=user_prompt
            )
            
            if fixed_code and isinstance(fixed_code, Code):
                implemented_changes.append({
                    "type": "missing_validation",
                    "validation": validation,
                    "change_summary": fixed_code.change_summary,
                    "code": fixed_code.code
                })
                current_code = fixed_code.code  # Update with the fixed code

        # Process validation errors
        for error in review.errors_in_existing_validations:
            user_prompt = f"""
            Fix validation error at line {error.line_number}:
            Error: {error.description}
            Suggested fix: {error.suggested_fix}
            
            Original code:
            {current_code}
            
            Requirements:
            1. Correct the validation logic
            2. Preserve surrounding functionality
            3. Add comments explaining the fix
            4. Return the complete updated code
            """
            
            # Get the fix from LLM
            fixed_code = analyzer.ask_llm(
                prompt=user_prompt
            )
            
            if fixed_code and isinstance(fixed_code, Code):
                implemented_changes.append({
                    "type": "validation_fix",
                    "line_number": error.line_number,
                    "error": error.description,
                    "change_summary": fixed_code.change_summary,
                    "code": fixed_code.code
                })
                current_code = fixed_code.code  # Update with the fixed code

        # Write the modified code back
        with open(code_file, "w") as f:
            f.write(current_code)

        # Commit changes
        commit_message = f"Implemented review comments for {contract_name}.{function_name}"
        context.commit(commit_message)

        # Update status if callback provided
        if update_status_fn:
            update_status_fn(
                submission["submission_id"],
                contract_name,
                function_name,
                "implement_review"
            )

        return {
            "status": "success",
            "code_file": code_file,
            "message": f"Successfully implemented {len(implemented_changes)} review comments"
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "error_details": str(e)
        }