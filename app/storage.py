import os
import json
import logging
from typing import Dict, Any, Optional
from google.cloud import storage
from google.api_core.exceptions import GoogleAPIError, NotFound
from flask import Blueprint, jsonify
from app.clients import storage_client
from app.tools import authenticate
from functools import wraps
from app.clients import datastore_client
from flask import request
from app.context import prepare_context_lazy

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "ilumina-analysis")

class GCSStorage:
    """Google Cloud Storage client with robust error handling"""
    
    def __init__(self):
        """
        Initialize GCS client with minimal permissions check.
        Compatible with older versions of google-cloud-storage.
        """
        try:
            # Validate configuration
            self.bucket_name = os.getenv("GCS_BUCKET_NAME")

            if os.getenv("USE_CREDENTIAL_FILE") == "true":
                creds_path = os.getenv("GCS_CREDENTIALS_PATH")
                if not creds_path or not os.path.exists(creds_path):
                    raise ValueError("Service account JSON file not found")
                self.client = storage.Client.from_service_account_json(creds_path)
            else:
                # Use injected credentials
                self.client = storage.Client()

            if not self.bucket_name:
                raise ValueError("GCS_BUCKET_NAME not set in .env")

            # Initialize client (without retry parameter)
            
            self.bucket = self.client.bucket(self.bucket_name)
            
            # Lightweight permission check
            #self._verify_permissions()
            
            logger.info(f"Successfully connected to GCS bucket: {self.bucket_name}")

        except Exception as e:
            logger.error(f"GCS initialization failed: {str(e)}")
            raise

    def _verify_permissions(self):
        """Verify we have basic object read/write permissions"""
        try:
            test_blob = self.bucket.blob("permission_test.tmp")
            test_blob.upload_from_string("test")
            test_blob.delete()
        except GoogleAPIError as e:
            if "Permission denied" in str(e):
                raise PermissionError(
                    f"Service account lacks permissions on {self.bucket_name}. "
                    "Required roles: storage.objectAdmin"
                ) from e
            raise

    def write_json(self, blob_name: str, data: Dict[str, Any]) -> bool:
        """
        Safely write JSON data to GCS
        Args:
            blob_name: Path like "predify/analysis.json"
            data: Dictionary to serialize as JSON
        Returns:
            True if successful
        """
        try:
            blob = self.bucket.blob(blob_name)
            blob.upload_from_string(
                json.dumps(data, indent=2),
                content_type="application/json"
            )
            logger.info(f"Stored JSON at gs://{self.bucket_name}/{blob_name}")
            return True
        except GoogleAPIError as e:
            logger.error(f"Failed to write {blob_name}: {str(e)}")
            raise

    def read_json(self, blob_name: str) -> Optional[Dict[str, Any]]:
        """
        Read JSON data from GCS with error handling
        Args:
            blob_name: Path to the JSON file
        Returns:
            Parsed JSON or None if not found
        """
        try:
            blob = self.bucket.blob(blob_name)
            if not blob.exists():
                return None
            content = blob.download_as_text()
            return json.loads(content)
        except NotFound:
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in {blob_name}: {str(e)}")
            raise
        except GoogleAPIError as e:
            logger.error(f"GCS read failed for {blob_name}: {str(e)}")
            raise

    def list_files(self, prefix: str = "") -> list:
        """
        List files with prefix (e.g., "predify/")
        Returns:
            List of blob names
        """
        try:
            return [blob.name for blob in self.bucket.list_blobs(prefix=prefix)]
        except GoogleAPIError as e:
            logger.error(f"Failed to list files: {str(e)}")
            raise

    def delete_file(self, blob_name: str) -> bool:
        """Safely delete a file"""
        try:
            blob = self.bucket.blob(blob_name)
            if blob.exists():
                blob.delete()
                return True
            return False
        except GoogleAPIError as e:
            logger.error(f"Failed to delete {blob_name}: {str(e)}")
            raise

def upload_to_gcs(blob_name, file_path):
    """Uploads a file to Google Cloud Storage."""
    bucket = storage_client.bucket(BUCKET_NAME)
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(file_path)

storage_blueprint = Blueprint('storage', __name__)

@storage_blueprint.route('/api/project_summary/<submission_id>', methods=['GET'])
@authenticate
def get_project_summary(submission_id):
    """Fetch project summary from Google Cloud Storage."""
    bucket = storage_client.bucket(BUCKET_NAME)
    submission = datastore_client.get(datastore_client.key("Submission", submission_id))
    if not submission:
        return jsonify({"error": "Submission not found"}), 404
    context = prepare_context_lazy(submission)
    blob = bucket.blob(context.gcs_summary_path_from_version(submission["summary_version"]))

    if not blob.exists():
        return jsonify({"error": "Project summary not found"}), 404

    summary_data = blob.download_as_text()
    return jsonify({"project_summary": summary_data}), 200

@storage_blueprint.route('/api/actors_summary/<submission_id>', methods=['GET'])
@authenticate
def get_actors_summary(submission_id):
    """Fetch actors summary from Google Cloud Storage."""
    submission = datastore_client.get(datastore_client.key("Submission", submission_id))
    if not submission:
        return jsonify({"error": "Submission not found"}), 404
    bucket = storage_client.bucket(BUCKET_NAME)

    context = prepare_context_lazy(submission)
    blob = bucket.blob(context.gcs_actor_summary_path_from_version(submission["summary_version"]))

    if not blob.exists():
        return jsonify({"error": "Actors summary not found"}), 404

    summary_data = blob.download_as_text()
    return jsonify({"actors_summary": summary_data}), 200