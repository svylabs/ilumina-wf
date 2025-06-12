# implement_review_comments.py
import os
import json
from typing import Dict, List, Optional
from app.models import ActionReview, Review, Code
from app.three_stage_llm_call import ThreeStageAnalyzer
from app.context import prepare_context

def implement_review_comments(
    submission, 
    contract_name: str, 
    function_name: str
) -> Dict:
    try:
        context = prepare_context(submission, optimize=False, needs_parallel_workspace=False)
        
        # Path setup for review file
        reviews_dir = os.path.join(context.simulation_path(), "reviews", "actions")
        review_file = os.path.join(reviews_dir, f"{contract_name}_{function_name}.json")
        
        # Path setup for code file
        code_file = os.path.join(context.simulation_path(), "simulation", "actions", 
                               f"{contract_name}_{function_name}.ts")
        
        # Validate files exist
        if not os.path.exists(review_file):
            return {
                "status": "error",
                "message": f"Review file not found: {review_file}"
            }
        if not os.path.exists(code_file):
            return {
                "status": "error", 
                "message": f"Action code file not found: {code_file}"
            }

        # Load review data with proper validation
        with open(review_file, "r") as f:
            review_data = json.load(f)
            
            # Ensure required fields are present
            if "reviews" not in review_data:
                review_data["reviews"] = []
            if "overall_assessment" not in review_data:
                review_data["overall_assessment"] = []
                
            action_review = ActionReview(**review_data)

        # Load original code
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

        analyzer = ThreeStageAnalyzer(Code, system_prompt=system_prompt)
        implemented_changes = []
        current_code = original_code
        
        # Process each review item
        for review in action_review.reviews:
            if not isinstance(review, Review):
                continue  # Skip invalid review items
                
            user_prompt = f"""
            Fix issue in {review.function_name} function:
            
            Issue type: {review.description}
            Suggested fix: {review.suggested_fix}
            
            Original code:
            {current_code}
            
            Requirements:
            1. Correct the issue while preserving functionality
            2. Add comments explaining the fix if needed
            3. Preserve the original functionality
            4. Return the complete updated code
            """
            
            # Get the fix from LLM
            fixed_code = analyzer.ask_llm(prompt=user_prompt)
            
            if fixed_code and isinstance(fixed_code, Code):
                implemented_changes.append({
                    "function": review.function_name,
                    "line_number": review.line_number,
                    "issue": review.description,
                    "suggested_fix": review.suggested_fix,
                    "change_summary": fixed_code.change_summary,
                    "code_diff": _generate_diff(current_code, fixed_code.code)
                })
                current_code = fixed_code.code  # Update with the fixed code

        return {
            "status": "success",
            "original_code": original_code,
            "modified_code": current_code,
            "changes": implemented_changes,
            "message": f"Successfully processed {len(implemented_changes)} review comments",
            "overall_assessment": action_review.overall_assessment
        }

    except json.JSONDecodeError as e:
        return {
            "status": "error",
            "message": f"Invalid JSON in review file: {str(e)}"
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "error_details": str(e)
        }

def _generate_diff(old_code: str, new_code: str) -> str:
    """
    Generate a simple diff between old and new code.
    For a real implementation, you might want to use a proper diff library.
    """
    old_lines = old_code.split('\n')
    new_lines = new_code.split('\n')
    
    diff = []
    for i, (old_line, new_line) in enumerate(zip(old_lines, new_lines)):
        if old_line != new_line:
            diff.append(f"Line {i+1}:")
            diff.append(f"- {old_line}")
            diff.append(f"+ {new_line}")
            diff.append("")
    
    return '\n'.join(diff)