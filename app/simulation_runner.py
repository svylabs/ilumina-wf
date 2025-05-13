import datetime
import subprocess
from google.cloud import datastore, storage
from .clients import datastore_client, storage_client
import uuid
from .context import RunContext
import os
import traceback

BUCKET_NAME = "ilumina-simulation-logs"

class SimulationRun:
    def __init__(self, simulation_id, submission_id, status, type="run", batch_id=None, description="", num_simulations=1, branch="main"):
        self.simulation_id = simulation_id
        self.submission_id = submission_id
        self.status = status
        self.batch_id = batch_id
        self.description = description
        self.type = type
        self.branch = branch
        self.num_simulations = num_simulations
        self.created_at = datetime.datetime.now()
        self.updated_at = datetime.datetime.now()

    def create(self):
        """Create a new simulation run in the datastore."""
        key = datastore_client.key("SimulationRun", self.simulation_id)
        entity = datastore.Entity(key=key)
        entity.update({
            "simulation_id": self.simulation_id,
            "submission_id": self.submission_id,
            "status": self.status,
            "type": self.type,
            "batch_id": self.batch_id,
            "description": self.description,
            "branch": self.branch,
            "num_simulations": self.num_simulations,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        })
        datastore_client.put(entity)

    def update_status(self, status, metadata=None):
        """Update the status of the simulation run."""
        key = datastore_client.key("SimulationRun", self.simulation_id)
        entity = datastore_client.get(key)

        if entity:
            entity.update({
                "status": status,
                "updated_at": datetime.datetime.now()
            })

            if metadata:
                for key, value in metadata.items():
                    entity[key] = value
                    if key not in entity.exclude_from_indexes:
                        entity.exclude_from_indexes.add(key)

            datastore_client.put(entity)
        else:
            raise ValueError(f"SimulationRun with ID {self.simulation_id} not found.")
        
    @classmethod
    def load(cls, simulation_id):
        """Load a simulation run from the datastore."""
        key = datastore_client.key("SimulationRun", simulation_id)
        entity = datastore_client.get(key)

        if entity:
            return cls(
                simulation_id=entity["simulation_id"],
                submission_id=entity["submission_id"],
                status=entity["status"],
                type=entity.get("type", "run"),
                batch_id=entity.get("batch_id"),
                description=entity.get("description", ""),
                num_simulations=entity.get("num_simulations", 1),
                branch=entity.get("branch", "main")
            )
        else:
            raise ValueError(f"SimulationRun with ID {simulation_id} not found.")


class SimulationRunner:
    def __init__(self, context: RunContext, simulation):
        self.context = context
        self.simulation = simulation
        self.simulation_id = simulation.simulation_id

    def run_batch(self, total_workers, worker_id):
        self._update_simulation_status("in_progress")
        all_simulations = self.get_runs_by_batch(self.simulation.submission_id, self.simulation_id)
        simulations_for_worker = []
        total_run = 0
        for i, all_simulations in enumerate(all_simulations):
            if i % total_workers == worker_id:
                total_run += 1
                simulations_for_worker.append(all_simulations)
        
        # Run the simulation script for each simulation
        for simulation in simulations_for_worker:
            if simulation.type == "run" and simulation.status != "error" or simulation.status != "success":
                runner = SimulationRunner(self.context, simulation)
                runner.run()

        
        all_simulations = self.get_runs_by_batch(self.simulation.submission_id)
        success = 0
        failed = 0
        scheduled = 0
        for simulation in all_simulations:
            if simulation.type == "run":
                if simulation.status == "success":
                    success += 1
                elif simulation.status == "error":
                    failed += 1
                else:
                    scheduled += 1

        status = "success" if failed == 0 else "error"
                
        self._update_simulation_status("success", metadata={
            "total": total_run,
            "success": success,
            "failed": failed,
            "scheduled": scheduled})



    def run(self):
        """Start the simulation and track its status."""
        # Record the start of the simulation
        self._update_simulation_status("in_progress")
        returncode = 0

        try:
            # Run the simulation script
            result = subprocess.run(["/bin/bash", "scripts/run_simulation.sh", self.simulation.simulation_id, self.context.simulation_path()], 
                                    capture_output=True,
                                    check=True,
                                    text=True)
            returncode = result.returncode

            # Check the result
            if result.returncode == 0:
                self._update_simulation_status("success", metadata={
                    "return_code": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr 
                })
                self._upload_log(self.context.simulation_log_path(self.simulation_id))
            else:
                self._update_simulation_status("error", metadata={
                    "return_code": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr 
                })
                if (os.path.exists(self.context.simulation_log_path(self.simulation_id))):
                    self._upload_log(self.context.simulation_log_path(self.simulation_id))

        except Exception as e:
            error = traceback.format_exc()
            print(f"Error during simulation: {error}")
            self._update_simulation_status("error", metadata={
                "return_code": returncode,
                "log": error,
                "no_log": True
            })
            if (os.path.exists(self.context.simulation_log_path(self.simulation_id))):
                self._upload_log(self.context.simulation_log_path(self.simulation_id))

    def _update_simulation_status(self, status, metadata=None):
        """Update the simulation status in the datastore."""
        key = datastore_client.key("SimulationRun", self.simulation_id)
        entity = datastore_client.get(key)

        entity.update({
            "status": status,
            "updated_at": datetime.datetime.now()
        })

        if metadata:
            for key, value in metadata.items():
                entity[key] = value
                if key not in entity.exclude_from_indexes:
                    entity.exclude_from_indexes.add(key)

        datastore_client.put(entity)

    def _upload_log(self, log_file_path):
        """Upload the simulation log from a file to Google Cloud Storage."""
        bucket = storage_client.bucket(self.bucket_name)
        blob = bucket.blob(f"simulation_logs/{self.simulation_id}.log")
        with open(log_file_path, 'rb') as log_file:
            blob.upload_from_file(log_file)
        os.remove(log_file_path)

    @classmethod
    def get_runs(cls, submission_id):
        """Fetch all simulation runs from the datastore."""
        query = datastore_client.query(kind="SimulationRun")
        query.add_filter("submission_id", "=", submission_id)
        query.add_filter("batch_id", "is", None)
        results = list(query.fetch())
        results = sorted(results, key=lambda x: x['created_at'], reverse=True)
        
        for result in results:
            if "no_log" in result or ("type" in result and result["type"] == "batch"):
                result["log_url"] = None
            else:
                result["log_url"] = cls.get_signed_simulation_log(result["simulation_id"])
        return results

    @classmethod
    def get_runs_by_batch(cls, submission_id, batch_id, with_log=True):
        """Fetch simulation runs by batch ID."""
        query = datastore_client.query(kind="SimulationRun")
        query.add_filter("submission_id", "=", submission_id)
        query.add_filter("batch_id", "=", batch_id)
        results = list(query.fetch())
        results = sorted(results, key=lambda x: x['simulation_id'], reverse=True)
        if with_log == True:
            for result in results:
                if "no_log" in result:
                    result["log_url"] = None
                else:
                    result["log_url"] = cls.get_signed_simulation_log(result["simulation_id"])
        return results
    
    @classmethod
    def get_signed_simulation_log(cls, simulation_id):
        """Get a signed URL for the simulation log."""
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(f"simulation_logs/{simulation_id}.log")
        url = blob.generate_signed_url(expiration=datetime.timedelta(minutes=15), 
                                       method="GET",
                                       version='v4',
                                       response_disposition='inline'
                            )
        return url
