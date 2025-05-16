#!/usr/bin/env python3
import json
import os
import re
import random
from pathlib import Path
from typing import Dict, List, Optional
from .context import RunContext
from .three_stage_llm_call import ThreeStageAnalyzer
from .models import ActionInstruction
from .compiler import Compiler
from jinja2 import FileSystemLoader, Environment
from .models import Actors

scaffold_templates = FileSystemLoader('scaffold')
env = Environment(loader=scaffold_templates)

class Scaffolder:
    def __init__(self, context: RunContext):
        self.context = context
        self.actions_dir = os.path.join(context.simulation_path(), "simulation", "actions")
        os.makedirs(self.actions_dir, exist_ok=True)
        
        self.actors = self.context.actor_summary()

    def scaffold(self):
        # setupActions
        self.setupActions()
        # setupActors
        self.setupActors()
        # setupSnapshotProvider
        self.setupSnapshotProvider()

    def setupActors(self):
        
        pass

    def setupSnapshotProvider(self):
        pass

    def setupActions(self):
        """Generate action files for all actors and actions"""
        # First compile contracts to get ABIs
        #self.compiler.compile()
        
        for actor in self.actors:
            for action in actor["actions"]:
                self._generate_action_file(
                    action["name"]
                )

    def _solidity_to_ts_type(self, solidity_type: str) -> str:
        """Convert Solidity type to TypeScript type"""
        type_map = {
            "address": "string",
            "bool": "boolean",
            "string": "string",
            "uint": "bigint",
            "int": "bigint",
            "bytes": "string"
        }
        
        for solidity, ts in type_map.items():
            if solidity_type.startswith(solidity):
                return ts
            
        return "any"

    def _sanitize_for_filename(self, name: str) -> str:
        """Sanitize name for safe filename: lowercase, underscore-separated."""
        cleaned = re.sub(r'[^\w\s]', '', name)  # Remove non-alphanum (keep spaces)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()  # Normalize whitespace
        return cleaned.lower().replace(' ', '_')
    
    def _sanitize_for_classname(self, name: str) -> str:
        """Sanitize name to generate PascalCase class name."""
        cleaned = re.sub(r'[^\w\s]', '', name)  # Remove non-alphanum (keep spaces)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        return ''.join(word.capitalize() for word in cleaned.split())

    def _generate_time_offset(self) -> int:
        """Generate a reasonable time offset in seconds using context.prng"""
        return self.context.prng.randint(3600, 259200)  # 1 hour to 3 days

    def _generate_param_init_code(self, param_name: str, param_type: str, function_name: str) -> str:
        """Generate initialization code for a parameter using context.prng"""
        if param_name.lower().endswith("address"):
            return f"const {param_name} = actor.account.value; // Using actor's address"
        
        if "strategy" in param_name.lower():
            return f"const {param_name} = context.getStrategy('{param_name}'); // Get strategy from context"
        
        if "time" in param_name.lower():
            offset = self._generate_time_offset()
            return f"const {param_name} = Math.floor(Date.now() / 1000) + {offset}; // Current timestamp with offset"
        
        if param_type.startswith("uint") or param_type.startswith("int"):
            bits = param_type[4:] if param_type.startswith("uint") else param_type[3:]
            max_val = 2 ** (int(bits) if bits else 256) - 1
            return f"const {param_name} = new BigNumber(context.prng.next().toFixed()).mod({max_val}); // Random {param_type}"
        
        if param_type == "bool":
            return f"const {param_name} = context.prng.next() > 0.5; // Random boolean"
        
        if param_type == "string":
            return f"const {param_name} = `{function_name}_${{context.prng.next().toString(36).substring(2, 8)}}`; // Random string"
        
        if param_type.startswith("bytes"):
            size = int(param_type[5:]) if param_type[5:] else 32
            return (
                f"const {param_name} = ethers.hexlify(Uint8Array.from("
                f"Array.from({{length: {size}}}, () => Math.floor(context.prng.next() * 256)))); // Random bytes"
            )
        
        return f"const {param_name} = context.getParam('{param_name}') || '{param_name}_default'; // Get from context or use default"

    def _clean_generated_code(self, code: str) -> str:
        """Clean and format generated TypeScript code"""
        code = code.replace("```typescript", "").replace("```", "").strip()
        lines = code.split('\n')
        imports = []
        other_lines = []
        seen_imports = set()
        
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("import"):
                if stripped not in seen_imports:
                    seen_imports.add(stripped)
                    imports.append(line)
            else:
                other_lines.append(line)
        
        imports.sort()
        return '\n'.join(imports + other_lines)

    def _generate_action_file(self, action_name):
        filename = f"{self._sanitize_for_filename(action_name)}.ts"
        filepath = os.path.join(self.actions_dir, filename)
        
        if os.path.exists(filepath):
            return
            
        sanitized_class_name = self._sanitize_for_classname(action_name)
        action_template = env.get_template("action.ts.j2")
        class_name = sanitized_class_name + "Action"

        action_content = action_template.render({
            "action_name": sanitized_class_name,
        })

        with open(filepath, "w") as f:
            f.write(action_content)

        self.context.commit(f"Generated action: {sanitized_class_name}Action")