import os

def ensure_directory_exists(directory_path):
    """Ensure a directory exists, create it if it doesn't."""
    if not os.path.exists(directory_path):
        os.makedirs(directory_path)

def clone_repo(repo_url, destination_path):
    """Clone a repository if it doesn't already exist."""
    if not os.path.exists(destination_path):
        os.system(f"git clone {repo_url} {destination_path}")
    else:
        print(f"Repository already exists at {destination_path}")
        os.system(f"cd {destination_path} && git stash && git pull")