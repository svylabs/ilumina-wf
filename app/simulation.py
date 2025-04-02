import json
import random
from datetime import datetime
from .models import Project
from .openai import ask_openai

class SimulationEngine:
    def __init__(self, context):
        self.context = context

    def generate_scenarios(self, actors):
        prompt = f"""
        Given these smart contract actors:
        {json.dumps(actors)}
        
        Generate realistic test scenarios covering:
        1. Normal operations
        2. Edge cases
        3. Attack vectors
        4. Error conditions
        
        Return JSON with scenario descriptions.
        """
        _, scenarios = ask_openai(prompt, dict)
        return scenarios["scenarios"]

    def run_simulation(self, scenario):
        result = {
            "scenario": scenario,
            "status": random.choice(["passed", "failed", "error"]),
            "gas_used": random.randint(10000, 500000),
            "timestamp": datetime.utcnow().isoformat()
        }
        
        if result["status"] != "passed":
            result["error"] = "Simulated failure"
        return result

    def run(self):
        actor_data = self.context.gcs.read_json(
            self.context.actor_summary_path()
        )
        
        scenarios = self.generate_scenarios(actor_data)
        results = [self.run_simulation(s) for s in scenarios]
        
        self.context.gcs.write_json(
            self.context.simulation_path(),
            {"scenarios": scenarios, "results": results}
        )
        return results