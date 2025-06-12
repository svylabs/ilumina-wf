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
        review_file = os.path.join(reviews_dir, f"{contract_name}_{function_name}.json")
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

        # Process all review comments in a single list
        for review_item in getattr(review, 'reviews', []):
            user_prompt = f"""
            Review comment for function '{review_item.function_name}' at line {review_item.line_number}:
            Description: {review_item.description}
            Suggested fix: {review_item.suggested_fix}

            Original code:
            {current_code}

            Requirements:
            1. Apply the suggested fix and address the review comment
            2. Add comments explaining the change
            3. Preserve the original functionality
            4. Return the complete updated code
            """
            analyzer = ThreeStageAnalyzer(Code, system_prompt=system_prompt)
            fixed_code = analyzer.ask_llm(prompt=user_prompt)
            if fixed_code and isinstance(fixed_code, Code):
                implemented_changes.append({
                    "line_number": review_item.line_number,
                    "function_name": review_item.function_name,
                    "description": review_item.description,
                    "change_summary": fixed_code.change_summary,
                    "code": fixed_code.code
                })
                current_code = fixed_code.code  # Update with the fixed code

        # Only return the updated code and the change summary
        return {
            "status": "success",
            "code": current_code,
            "implemented_changes": implemented_changes,
            "message": f"Successfully implemented {len(implemented_changes)} review comments (not saved, only returned)"
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "error_details": str(e)
        }