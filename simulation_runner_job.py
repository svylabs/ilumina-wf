import os
import json
import dotenv
dotenv.load_dotenv()
import logging
import sys
from app.simulation_runner import SimulationRunner, SimulationRun
from app.context import prepare_context
from app.clients import datastore_client

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
    #print(f"Submission: {submission}")
    #print(f"Simulation: {simulation}")

    context = prepare_context(submission, optimize=False, contract_branch=simulation.branch or "main")

    if simulation.type == "run":
        runner = SimulationRunner(context, simulation)
        runner.run()
    elif simulation.type == "batch":
        worker_id = int(os.getenv("CLOUD_RUN_TASK_INDEX", 0))
        total_workers = int(os.getenv("CLOUD_RUN_TASK_COUNT", 1))
        runner = SimulationRunner(context, simulation)
        runner.run_batch(total_workers, worker_id)

if __name__ == "__main__":
    main()
    