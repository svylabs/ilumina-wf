import os
import subprocess
import shutil
import json
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class GitUtils:
    @staticmethod
    def setup_ilumina_project(
        template_repo_url: str,
        new_repo_path: str,
        new_origin_url: str,
        project_name: str
    ) -> Dict[str, Any]:
        """
        Setup ilumina simulation project from template
        Args:
            template_repo_url: URL of ilumina template
            new_repo_path: Path for new repository
            new_origin_url: GitHub URL for new repository
            project_name: Name of the project
        """
        try:
            # Clone template
            subprocess.run([
                "git", "clone",
                "--depth", "1",
                template_repo_url,
                new_repo_path
            ], check=True)

            # Remove template's git history
            shutil.rmtree(os.path.join(new_repo_path, ".git"))

            # Initialize new repository
            subprocess.run(["git", "init"], cwd=new_repo_path, check=True)

            # Install ilumina
            subprocess.run([
                "npm", "install", "--save-dev", "@svylabs/ilumina"
            ], cwd=new_repo_path, check=True)

            # Scaffold ilumina tests
            subprocess.run([
                "npx", "@svylabs/ilumina", "scaffold"
            ], cwd=new_repo_path, check=True)

            # Customize for project
            with open(os.path.join(new_repo_path, "package.json"), "r+") as f:
                data = json.load(f)
                data["name"] = f"{project_name}-simulation"
                f.seek(0)
                json.dump(data, f, indent=2)
                f.truncate()

            # Initial commit
            subprocess.run(["git", "add", "."], cwd=new_repo_path, check=True)
            subprocess.run([
                "git", "commit",
                "-m", f"Initialized ilumina simulation for {project_name}"
            ], cwd=new_repo_path, check=True)

            # Push to new origin
            subprocess.run([
                "git", "remote", "add", "origin", new_origin_url
            ], cwd=new_repo_path, check=True)
            subprocess.run([
                "git", "push", "-u", "origin", "main"
            ], cwd=new_repo_path, check=True)

            return {
                "status": "success",
                "ilumina_version": GitUtils.get_ilumina_version(new_repo_path)
            }

        except subprocess.CalledProcessError as e:
            logger.error(f"Setup failed: {str(e)}")
            raise RuntimeError(f"ilumina setup failed: {str(e)}")

    @staticmethod
    def get_ilumina_version(repo_path: str) -> str:
        """Get installed ilumina version"""
        try:
            result = subprocess.run(
                ["npm", "list", "@svylabs/ilumina"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.split('@')[-1].strip()
        except Exception:
            return "unknown"