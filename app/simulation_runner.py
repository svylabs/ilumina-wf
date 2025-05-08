import datetime
import subprocess
from google.cloud import datastore, storage
from .clients import datastore_client, storage_client
import uuid
from .context import RunContext

class SimulationRunner:
    def __init__(self, context: RunContext):
        self.context = context
        self.simulation_id = str(uuid.uuid4())
        self.bucket_name = "ilumina-simulation-logs"  # Replace with your GCS bucket name

    def start_simulation(self):
        """Start the simulation and track its status."""
        # Record the start of the simulation
        self._update_simulation_status("in_progress")

        try:
            # Run the simulation script
            result = subprocess.run(["/bin/bash", "scripts/run_simulation.sh", self.simulation_id], capture_output=True, text=True)

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
                self._upload_log(self.context.simulation_log_path(self.simulation_id))

        except Exception as e:
            self._update_simulation_status("error", metadata={
                "log": str(e),
            })

    def _update_simulation_status(self, status, metadata=None):
        """Update the simulation status in the datastore."""
        key = datastore_client.key("SimulationRun", self.simulation_id)
        entity = datastore_client.get(key)

        if not entity:
            entity = datastore.Entity(key=key)
            entity["created_at"] = datetime.datetime.now()

        entity.update({
            "simulation_id": self.simulation_id,
            "submission_id": self.context.submission_id,
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
        with open(log_file_path, 'r') as log_file:
            blob.upload_from_file(log_file)

    def get_runs(self):
        """Fetch all simulation runs from the datastore."""
        query = datastore_client.query(kind="SimulationRun")
        query.add_filter("submission_id", "=", self.context.submission_id)
        query.order = ["-created_at"]
        results = list(query.fetch())
        for result in results:
            result["log_url"] = self.get_signed_simulation_log()
        return results
    
    def get_signed_simulation_log(self):
        """Get a signed URL for the simulation log."""
        bucket = storage_client.bucket(self.bucket_name)
        blob = bucket.blob(f"simulation_logs/{self.simulation_id}.log")
        url = blob.generate_signed_url(expiration=datetime.timedelta(minutes=15), method="GET")
        return url
