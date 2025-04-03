import os
import subprocess
from typing import Optional
import logging

logger = logging.getLogger(__name__)

class GitUtils:
    @staticmethod
    def init_and_push_repo(repo_path: str, github_url: str) -> bool:
        """
        Initialize a local Git repository and push to GitHub
        Args:
            repo_path: Path to local repository
            github_url: GitHub repository URL
        Returns:
            True if successful
        """
        try:
            # Initialize local repository
            subprocess.run(["git", "init"], cwd=repo_path, check=True)
            
            # Create basic files
            with open(os.path.join(repo_path, "README.md"), "w") as f:
                f.write("# Simulation Repository\n\nThis repository contains simulation results.")
            
            # Add and commit
            subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
            subprocess.run(
                ["git", "commit", "-m", "Initial commit with simulation setup"],
                cwd=repo_path,
                check=True
            )
            
            # Add remote and push
            subprocess.run(["git", "remote", "add", "origin", github_url], cwd=repo_path, check=True)
            subprocess.run(["git", "push", "-u", "origin", "main"], cwd=repo_path, check=True)
            
            return True
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Git operation failed: {str(e)}")
            raise RuntimeError(f"Git operation failed: {str(e)}")
        except Exception as e:
            logger.error(f"Repository initialization failed: {str(e)}")
            raise RuntimeError(f"Repository initialization failed: {str(e)}")