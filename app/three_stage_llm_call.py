from pydantic import BaseModel, ValidationError
from typing import Type, Optional
from .openai import ask_openai
from abc import ABC, abstractmethod
from .models import IluminaOpenAIResponseModel
import json


class Verification(IluminaOpenAIResponseModel):
    is_change_needed: bool
    change_summary: list[str] = []

    def to_dict(self):
        return {
            "change_needed": self.is_change_needed,
            "change_summary": self.change_summary
        }


class ThreeStageAnalyzer:
    def __init__(self, model_class: Type[IluminaOpenAIResponseModel]):
        self.model_class = model_class
        self.draft = None

    def ask_llm(self, prompt: str) -> IluminaOpenAIResponseModel:
        self.prompt = prompt
        response = ask_openai("Step 1: Create draft\n\n" + prompt, self.model_class, task="analyze")
        self.draft = response[1]
        self.verification_result = self.verify_draft()
        print("Verification result:", self.verification_result.to_dict())
        return self.correct_draft()

    def verify_draft(self) -> IluminaOpenAIResponseModel:
        if self.draft is None:
            raise ValueError("Draft must be created first.")
        
        conversations = [
                {"role": "system", "content": "We will use a workflow style draft-verify-correct to create the final output necessary for the task."},
                {"role": "user", "content": "Step 1: Create draft\n\n" + self.prompt},
                {"role": "assistant","content": json.dumps(self.draft.to_dict())}
        ]
        
        prompt = f"Please verify the json draft and suggest any changes necessary"
        response = ask_openai(prompt, Verification, task="verify", conversations=conversations)
        self.verification_result = response[1]
        return self.verification_result
    
    def correct_draft(self):
        if self.verification_result is None:
            raise ValueError("Draft must be verified first.")
        if self.verification_result.is_change_needed:
            conversations = [
                {"role": "system", "content": "We will use a workflow style draft-verify-correct to create the final output necessary for the task."},
                {"role": "user", "content": "Step 1: Create draft\n\n" + self.prompt},
                {"role": "assistant","content": json.dumps(self.draft.to_dict())},
                {"role": "user", "content": "Step 2: Please verify the above json draft and suggest any changes necessary"},
                {"role": "assistant", "content": json.dumps(self.verification_result.to_dict())}
            ]
            prompt = "Step 3: Correct and finalize. Please correct the earlier draft based on the changes suggested"
            #prompt = f"Here is the original request from user: {self.prompt}\n\n"
            #prompt += f"Here is the draft created by the assistant: \n\n{self.draft.to_dict()}"
            #prompt += f"\n\nThe changes suggested by the assistant: {self.verification_result.to_dict()}"
            response = ask_openai(prompt, self.model_class, task="correct", conversations=conversations)
            print("Corrected draft:", response[1].to_dict())
            return response[1]
        else:
            return self.draft

    def finalize(self) -> BaseModel:
        if self.verified_draft is None:
            raise ValueError("Draft must be verified first.")
        self.final_output = self.process_stage("Finalize")
        return self.final_output