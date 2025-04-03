import os
import subprocess
import shutil
import json
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class GitUtils:
    @staticmethod
    def clone_template_and_init(
        template_repo_url: str,
        new_repo_path: str,
        new_origin_url: str,
        project_name: str
    ) -> Dict[str, Any]:
        """
        Clone template repo and initialize as new project
        Args:
            template_repo_url: URL of the template repository
            new_repo_path: Local path for the new repository
            new_origin_url: GitHub URL for the new repository
            project_name: Name of the project for customization
        Returns:
            Dictionary with operation results
        """
        try:
            # Clone template repository (shallow clone)
            subprocess.run([
                "git", "clone",
                "--depth", "1",
                template_repo_url,
                new_repo_path
            ], check=True, capture_output=True)
            
            # Remove template's git history
            shutil.rmtree(os.path.join(new_repo_path, ".git"))
            
            # Initialize new git repository
            subprocess.run(["git", "init"], cwd=new_repo_path, check=True)
            
            # Customize template files if needed
            GitUtils._customize_template(new_repo_path, project_name)
            
            # Initial commit
            subprocess.run(["git", "add", "."], cwd=new_repo_path, check=True)
            subprocess.run([
                "git", "commit",
                "-m", f"Initialized simulation repo for {project_name}"
            ], cwd=new_repo_path, check=True)
            
            # Set new origin and push
            subprocess.run([
                "git", "remote", "add", "origin", new_origin_url
            ], cwd=new_repo_path, check=True)
            subprocess.run([
                "git", "push", "-u", "origin", "main"
            ], cwd=new_repo_path, check=True)
            
            return {
                "status": "success",
                "local_path": new_repo_path,
                "template_source": template_repo_url
            }
            
        except subprocess.CalledProcessError as e:
            error_msg = f"Git operation failed: {e.stderr.decode().strip()}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        except Exception as e:
            logger.error(f"Repository setup failed: {str(e)}")
            raise RuntimeError(f"Repository setup failed: {str(e)}")

    @staticmethod
    def _customize_template(repo_path: str, project_name: str):
        """Customize template files for the new project"""
        try:
            # Update package.json if exists
            package_json_path = os.path.join(repo_path, "package.json")
            if os.path.exists(package_json_path):
                with open(package_json_path, "r+") as f:
                    data = json.load(f)
                    data["name"] = f"{project_name}-simulation"
                    f.seek(0)
                    json.dump(data, f, indent=2)
                    f.truncate()
            
            # Update README if exists
            readme_path = os.path.join(repo_path, "README.md")
            if os.path.exists(readme_path):
                with open(readme_path, "a") as f:
                    f.write(f"\n\n## Project Specific Setup\nThis simulation repository was created for {project_name}")
        except Exception as e:
            logger.warning(f"Template customization failed: {str(e)}")