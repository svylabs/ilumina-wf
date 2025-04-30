from pydantic import BaseModel, ValidationError
from typing import Type, Optional
from .openai import ask_openai
from abc import ABC, abstractmethod
from .models import IluminaOpenAIResponseModel


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
        response = ask_openai(prompt, self.model_class, task="analyze")
        self.draft = response[1]
        self.verification_result = self.verify_draft()
        print("Verification result:", self.verification_result.to_dict())
        return self.correct_draft()

    def verify_draft(self) -> IluminaOpenAIResponseModel:
        if self.draft is None:
            raise ValueError("Draft must be created first.")
        
        prompt = f"Please verify the following draft:\n\n{self.draft.to_dict()}"
        prompt += f"n\Here is the original request:\n\n{self.prompt}\n\n and suggest any changes needed. Assume the json structure is correct as it is."
        response = ask_openai(prompt, Verification, task="verify")
        self.verification_result = response[1]
        return self.verification_result
    
    def correct_draft(self):
        if self.verification_result is None:
            raise ValueError("Draft must be verified first.")
        if self.verification_result.is_change_needed:
            prompt = f"Please correct the following draft based on the changes needed:\n\n{self.draft.to_dict()}"
            prompt += f"\n\nThe changes needed: {self.verification_result.to_dict()}"
            response = ask_openai(prompt, self.model_class, task="correct")
            print("Corrected draft:", response[1].to_dict())
            return response[1]

    def finalize(self) -> BaseModel:
        if self.verified_draft is None:
            raise ValueError("Draft must be verified first.")
        self.final_output = self.process_stage("Finalize")
        return self.final_output