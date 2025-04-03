import os
import subprocess
import shutil
import json
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class GitUtils:
    @staticmethod
    def create_from_template(
        template_url: str,
        new_repo_path: str,
        new_origin_url: str,
        project_name: str
    ) -> Dict[str, Any]:
        """
        Create new repo from pre-scaffolded template
        Args:
            template_url: URL of pre-scaffolded template
            new_repo_path: Path for new repository
            new_origin_url: GitHub URL for new repository
            project_name: Name of the project
        """
        try:
            # Clone template (shallow clone)
            subprocess.run([
                "git", "clone",
                "--depth", "1",
                template_url,
                new_repo_path
            ], check=True)

            # Remove template's git history
            shutil.rmtree(os.path.join(new_repo_path, ".git"))

            # Initialize new repository
            subprocess.run(["git", "init"], cwd=new_repo_path, check=True)

            # Update project-specific configurations
            GitUtils._customize_project(new_repo_path, project_name)

            # Initial commit
            subprocess.run(["git", "add", "."], cwd=new_repo_path, check=True)
            subprocess.run([
                "git", "commit",
                "-m", f"Initialized simulation for {project_name}"
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
                "template_source": template_url
            }

        except subprocess.CalledProcessError as e:
            logger.error(f"Setup failed: {str(e)}")
            raise RuntimeError(f"Repository creation failed: {str(e)}")

    @staticmethod
    def _customize_project(repo_path: str, project_name: str):
        """Update project-specific files"""
        try:
            # Update package.json
            package_json = os.path.join(repo_path, "package.json")
            if os.path.exists(package_json):
                with open(package_json, "r+") as f:
                    data = json.load(f)
                    data["name"] = f"{project_name}-simulation"
                    f.seek(0)
                    json.dump(data, f, indent=2)
                    f.truncate()

            # Update README
            readme = os.path.join(repo_path, "README.md")
            if os.path.exists(readme):
                with open(readme, "a") as f:
                    f.write(f"\n\n## Project Specifics\nCreated for {project_name}")
        except Exception as e:
            logger.warning(f"Customization skipped: {str(e)}")