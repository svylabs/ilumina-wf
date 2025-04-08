'''
@app.route('/api/submission/<submission_id>/create_simulation_repo', methods=['POST'])
@authenticate
def create_simulation_repo(submission_id):
    """Create simulation repo from pre-scaffolded template"""
    try:
        data = request.get_json()
        project_name = data.get("project_name", f"project-{submission_id}")

        # Replace invalid characters with hyphens and convert to lowercase
        project_name = re.sub(r'[^a-zA-Z0-9-]', '-', project_name).lower()

        # Ensure no consecutive hyphens and strip leading/trailing hyphens
        project_name = re.sub(r'-+', '-', project_name).strip('-')

        # Create repository name
        repo_name = f"{project_name}-simulation"
        
        # 1. Create GitHub repository
        repo_data = github_api.create_repository(
            name=repo_name,
            private=True,
            description=f"Simulation repository for {project_name} (pre-scaffolded)"
        )
        
        # 2. Prepare local workspace
        repo_path = f"/tmp/{repo_name}"
        
        # 3. Clone template and initialize
        template_repo = os.getenv(
            "SIMULATION_TEMPLATE_REPO",
            "https://github.com/svylabs-com/ilumina-scaffolded-template.git"
        )
        
        GitUtils.create_from_template(
            template_url=template_repo,
            new_repo_path=repo_path,
            new_origin_url=repo_data["clone_url"],
            project_name=project_name
        )
        
        # Cleanup
        try:
            shutil.rmtree(repo_path)
        except Exception as e:
            app.logger.warning(f"Cleanup warning: {str(e)}")
        
        return jsonify({
            "status": "success",
            "repo_name": repo_name,
            "repo_url": repo_data["html_url"],
            "clone_url": repo_data["clone_url"],
            "template_source": template_repo,
            "scaffolded": False  # False because we used pre-scaffolded template
        }), 200
        
    except Exception as e:
        return jsonify({
            "error": str(e),
            "message": "Failed to create simulation repository"
        }), 500
        '''
