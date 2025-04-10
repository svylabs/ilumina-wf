import requests
from dotenv import load_dotenv
import os
import json
import logging
from typing import List, Dict, Optional

# Configure logging
logging.basicConfig(level=logging.DEBUG)  # Changed to DEBUG for more detailed logs
logger = logging.getLogger(__name__)

class GitHubAPI:
    def __init__(self):
        """
        Initialize GitHub API client with authentication.
        """
        self.token = os.getenv("GITHUB_TOKEN")
        logger.debug(f"Initializing GitHubAPI with token: {self.token[:4]}...")  # Log first 4 chars for security
        
        if not self.token:
            error_msg = "GITHUB_TOKEN environment variable not set"
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        self.headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Ilumina-WF/1.0"  # Required by GitHub API
        }
        self.base_url = "https://api.github.com"
        self.timeout = 15

    def get_repo_contents(self, repo_url: str, path: str = "") -> List[Dict]:
        """
        Get contents of a GitHub repository with enhanced debugging
        """
        try:
            owner, repo = self._parse_repo_url(repo_url)
            url = f"{self.base_url}/repos/{owner}/{repo}/contents/{path}"
            logger.debug(f"Constructed API URL: {url}")
            
            # Debug request headers
            logger.debug(f"Request headers: {json.dumps(self.headers, indent=2)}")
            
            response = requests.get(
                url,
                headers=self.headers,
                timeout=self.timeout
            )
            
            # Debug raw response
            logger.debug(f"Response status: {response.status_code}")
            logger.debug(f"Response headers: {dict(response.headers)}")
            
            self._check_response(response)
            
            # Debug successful response
            logger.debug(f"Successfully fetched contents from {repo_url}")
            return response.json()

        except requests.exceptions.RequestException as e:
            error_msg = f"Request failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            raise ValueError(f"GitHub API connection error: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}", exc_info=True)
            raise

    def _parse_repo_url(self, repo_url: str) -> tuple:
        """Parse GitHub URL with better error handling"""
        try:
            clean_url = repo_url.strip().rstrip('/')
            if not clean_url.startswith('https://github.com/'):
                raise ValueError("URL must start with https://github.com/")
                
            parts = clean_url.replace("https://github.com/", "").split("/")
            if len(parts) < 2:
                raise ValueError("URL must contain owner/repo")
                
            owner, repo = parts[0], parts[1]
            logger.debug(f"Parsed URL: owner={owner}, repo={repo}")
            return owner, repo
            
        except Exception as e:
            error_msg = f"Invalid GitHub URL '{repo_url}': {str(e)}"
            logger.error(error_msg)
            raise ValueError(error_msg)

    def _check_response(self, response: requests.Response) -> None:
        """Enhanced response validation"""
        try:
            response_data = response.json()
        except ValueError:
            response_data = {}
            
        if response.status_code == 401:
            error_msg = response_data.get("message", "Authentication failed")
            logger.error(f"Auth error: {error_msg}")
            if "Bad credentials" in error_msg:
                raise ValueError(
                    "Invalid GitHub token. Please:\n"
                    "1. Check your .env file has GITHUB_TOKEN\n"
                    "2. Verify the token at https://github.com/settings/tokens\n"
                    "3. Ensure token has 'repo' scope"
                )
            raise ValueError(f"GitHub API authentication error: {error_msg}")
            
        elif response.status_code == 403:
            rate_limit = response.headers.get("X-RateLimit-Remaining", "unknown")
            reset_time = response.headers.get("X-RateLimit-Reset", "")
            logger.error(f"Rate limit: {rate_limit} remaining, resets at {reset_time}")
            raise ValueError(
                f"Rate limit exceeded. Remaining: {rate_limit}\n"
                f"Reset time: {reset_time}"
            )
            
        elif response.status_code == 404:
            raise ValueError("Repository not found or access denied")
            
        elif not response.ok:
            error_msg = response_data.get("message", f"HTTP {response.status_code}")
            logger.error(f"API error: {error_msg}")
            raise ValueError(f"GitHub API error: {error_msg}")

    def get_default_branch(self, repo_url: str) -> str:
        """Get default branch with debugging"""
        try:
            owner, repo = self._parse_repo_url(repo_url)
            url = f"{self.base_url}/repos/{owner}/{repo}"
            logger.debug(f"Fetching repo info from: {url}")
            
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            self._check_response(response)
            
            branch = response.json().get("default_branch", "main")
            logger.debug(f"Found default branch: {branch}")
            return branch
            
        except Exception as e:
            logger.warning(f"Using fallback 'main' branch due to: {str(e)}")
            return "main"

    def create_repository(self, name: str, private: bool = True, description: str = "") -> Dict:
        """
        Create a new GitHub repository
        Args:
            name: Repository name
            private: Whether repository should be private
            description: Repository description
        Returns:
            Dictionary with repository details
        """
        try:
            url = f"{self.base_url}/user/repos"
            data = {
                "name": name,
                "private": private,
                "description": description,
                "auto_init": False  # We'll initialize it ourselves
            }
            
            response = requests.post(
                url,
                headers=self.headers,
                json=data,
                timeout=self.timeout
            )
            
            self._check_response(response)
            return response.json()
            
        except requests.exceptions.RequestException as e:
            error_msg = f"Repository creation failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            raise ValueError(error_msg)

# Test function for direct execution
if __name__ == "__main__":
    try:
        load_dotenv()  # Load environment variables from .env file
        print("Testing GitHub API...")
        api = GitHubAPI()
        contents = api.get_repo_contents("https://github.com/svylabs/predify")
        print("Success! First 5 items:")
        for item in contents[:5]:
            print(f"- {item['name']} ({item['type']})")
    except Exception as e:
        print(f"Test failed: {str(e)}")