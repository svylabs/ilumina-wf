from pydantic import BaseModel
import json
import re

class Function(BaseModel):
    name: str
    summary: str
    inputs: list[str]
    outputs: list[str]

    def to_dict(self):
        return {
            "name": self.name,
            "summary": self.summary,
            "inputs": self.inputs,
            "outputs": self.outputs
        }

class Contract(BaseModel):
    path: str
    name: str
    type: str
    summary: str
    functions: list[Function]

    def to_dict(self):
        return {
            "path": self.path,
            "name": self.name,
            "type": self.type,
            "summary": self.summary,
            "functions": [f.to_dict() for f in self.functions]
        }

class Project(BaseModel):
    name: str
    summary: str
    type: str
    dev_tool: str
    contracts: list[Contract]

    def to_dict(self):
        return {
            "name": self.name,
            "summary": self.summary,
            "type": self.type,
            "dev_tool": self.dev_tool,
            "contracts": [c.to_dict() for c in self.contracts]
        }