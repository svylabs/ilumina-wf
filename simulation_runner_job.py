import os
import json
import dotenv
import logging
import sys
from app.simulation_runner import SimulationRunner, SimulationRun
from app.context import prepare_context
from app.clients import datastore_client

dotenv.load_dotenv()
logging.basicConfig(stream=sys.stdout, level=logging.INFO)

SIMULATION_ID = os.getenv("SIMULATION_ID")

def main():
    simulation = SimulationRun.load(SIMULATION_ID)
    if not simulation:
        logging.error(f"Simulation with ID {SIMULATION_ID} not found.")
        return
    logging.info(f"Starting simulation with ID {SIMULATION_ID}")

    key = datastore_client.key("Submission", simulation.submission_id)
    submission = datastore_client.get(key)

    context = prepare_context(submission.submission_id, optimize=False, contract_branch=simulation.branch or "main")

    if simulation.type == "run":
        runner = SimulationRunner(context, simulation)
        runner.run()
    elif simulation.type == "batch":
        runner = SimulationRunner(context, simulation)
        runner.run_batch()

if __name__ == "__main__":
    main()
    