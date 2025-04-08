import os

def create_github_repo(token, username, repo_name):
    """Create a private GitHub repository."""
    check_repo_command = (
        f"curl -H \"Authorization: token {token}\" "
        f"https://api.github.com/repos/{username}/{repo_name}"
    )
    repo_exists = os.system(check_repo_command) == 0

    if not repo_exists:
        create_repo_command = (
            f"curl -H \"Authorization: token {token}\" "
            f"-d '{{\"name\": \"{repo_name}\", \"private\": true}}' "
            f"https://api.github.com/user/repos"
        )
        os.system(create_repo_command)

def set_github_repo_origin_and_push(repo_path, github_repo_url):
    """Set the origin of the repo and push to GitHub."""
    os.system(f"cd {repo_path} && git remote set-url origin {github_repo_url}")
    os.system(f"cd {repo_path} && git push -u origin main")