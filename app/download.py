import subprocess
import os
import shutil
from datetime import datetime

class Downloader:
    def __init__(self, context):
        self.context = context

    def prepare_local_workspace(self):
        os.makedirs("/tmp/workspace", exist_ok=True)

    def clone_repository(self):
        repo_dir = f"/tmp/workspace/{self.context.repo_name}"
        if os.path.exists(repo_dir):
            shutil.rmtree(repo_dir)
        
        result = subprocess.run(
            ["git", "clone", "--depth", "1", self.context.repo_url, repo_dir],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"Clone failed: {result.stderr}")
        
        return repo_dir

    def cleanup(self):
        try:
            shutil.rmtree("/tmp/workspace")
        except Exception as e:
            print(f"Cleanup warning: {str(e)}")

    def download(self):
        try:
            self.prepare_local_workspace()
            repo_dir = self.clone_repository()
            
            self.context.initialize_run_log()
            return True
        finally:
            self.cleanup()