import os
import subprocess
import requests

def create_github_repo(token, username, repo_name):
    """Create a private GitHub repository."""
    headers = {"Authorization": f"token {token}"}
    check_repo_url = f"https://api.github.com/repos/{username}/{repo_name}"

    response = requests.get(check_repo_url, headers=headers)
    if response.status_code == 200:
        print(f"Repository exists: {response.json()}")
    else:
        create_repo_url = "https://api.github.com/user/repos"
        payload = {"name": repo_name, "private": True}
        create_response = requests.post(create_repo_url, headers=headers, json=payload)
        if create_response.status_code == 201:
            print(f"Repository created: {create_response.json()}")
        else:
            print(f"Failed to create repository: {create_response.status_code}, {create_response.json()}")

def set_github_repo_origin_and_push(repo_path, github_repo_url):
    """Set the origin of the repo and push to GitHub."""
    os.system(f"cd {repo_path} && git remote set-url origin {github_repo_url}")
    os.system(f"cd {repo_path} && git push -u origin main")