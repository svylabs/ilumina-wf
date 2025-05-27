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
    def __init__(self, model_class: Type[IluminaOpenAIResponseModel], system_prompt=""):
        self.model_class = model_class
        self.draft = None
        base_system_prompt = "You are an AI assistant and will use a workflow draft-verify-correct to create the final output necessary for the task, and optionally followed by checks to see if guidelines by users are met with regard to the output."
        if system_prompt != "":
            base_system_prompt += f"\n\n{system_prompt}"
        self.conversations = [
            {"role": "system", "content": base_system_prompt},
        ]

    def ask_llm(self, prompt: str, guidelines=[]) -> IluminaOpenAIResponseModel:
        self.prompt = prompt
        new_conversation = {
            "role": "user",
            "content": "Step 1: Create draft\n\n" + prompt
        }
        self.conversations.append(new_conversation)
        response = ask_openai("Step 1: Create draft\n\n" + prompt, self.model_class, task="analyze")
        self.draft = response[1]
        self.verification_result = self.verify_draft()
        print("Verification result:", self.verification_result.to_dict())
        if len(guidelines) == 0:
            return self.correct_draft()
        else:
            self.draft = self.correct_draft()
            self.conversations.append(
                {
                    "role": "assistant",
                    "content": json.dumps(self.draft.to_dict())
                }
            )
            response = ask_openai(
                f"Please check if the above json draft meets the following guidelines: {guidelines}",
                Verification,
                conversations=self.conversations
            )
            self.verification_result = response[1]
            print("Guideline verification:", json.dumps(self.verification_result.to_dict()))
            if self.verification_result.is_change_needed:
                return self.correct_draft()
            else:
                return self.draft
                



    def verify_draft(self) -> IluminaOpenAIResponseModel:
        if self.draft is None:
            raise ValueError("Draft must be created first.")
        
        self.conversations.append(
            {"role": "assistant","content": json.dumps(self.draft.to_dict())}
        )
        
        prompt = f"Step 2: Please verify the json draft and suggest any changes necessary"
        response = ask_openai(prompt, Verification, task="verify", conversations=self.conversations)
        self.verification_result = response[1]
        self.conversations.append(
            {"role": "user", "content": prompt}
        )
        self.conversations.append(
                {"role": "assistant", "content": json.dumps(self.verification_result.to_dict())}
            )
            
        return self.verification_result
    
    def correct_draft(self, guidelines=[]):
        if self.verification_result is None:
            raise ValueError("Draft must be verified first.")
        if self.verification_result.is_change_needed:
            prompt = "Step 3: Correct and finalize. Please correct the earlier draft based on the changes suggested"
            if len(guidelines) > 0:
                prompt += f" and use the following guidelines: {guidelines}"
            #prompt = f"Here is the original request from user: {self.prompt}\n\n"
            #prompt += f"Here is the draft created by the assistant: \n\n{self.draft.to_dict()}"
            #prompt += f"\n\nThe changes suggested by the assistant: {self.verification_result.to_dict()}"
            response = ask_openai(prompt, self.model_class, task="correct", conversations=self.conversations)
            print("Corrected draft:", response[1].to_dict())
            self.conversations.append(
                {"role": "user", "content": prompt}
            )
            self.conversations.append(
                {"role": "assistant", "content": json.dumps(response[1].to_dict())}
            )
            return response[1]
        else:
            return self.draft

    def finalize(self) -> BaseModel:
        if self.verified_draft is None:
            raise ValueError("Draft must be verified first.")
        self.final_output = self.process_stage("Finalize")
        return self.final_output