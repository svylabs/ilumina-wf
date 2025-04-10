import os
import subprocess

def create_github_repo(token, username, repo_name):
    """Create a private GitHub repository."""
    check_repo_command = (
        f"curl -H \"Authorization: token {token}\" "
        f"https://api.github.com/repos/{username}/{repo_name}"
    )
    repo_exists = os.system(check_repo_command)
    output = subprocess.run(check_repo_command, shell=True, check=True, capture_output=True)
    print(f"Repository exists: {repo_exists} {output.stdout.decode()}")

    if not repo_exists:
        create_repo_command = (
            f"curl -H \"Authorization: token {token}\" "
            f"-d '{{\"name\": \"{repo_name}\", \"private\": true}}' "
            f"https://api.github.com/user/repos"
        )
        print(f"Creating repository: {repo_name} {create_repo_command}")
        os.system(create_repo_command)

def set_github_repo_origin_and_push(repo_path, github_repo_url):
    """Set the origin of the repo and push to GitHub."""
    os.system(f"cd {repo_path} && git remote set-url origin {github_repo_url}")
    os.system(f"cd {repo_path} && git push -u origin main")