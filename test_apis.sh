#!/bin/bash

# Set the base URL of the API
BASE_URL="http://localhost:8080"

# Set the Authorization header
AUTH_HEADER="Authorization: Bearer my_secure_password"

# Test /begin_analysis
curl -X POST "$BASE_URL/begin_analysis" \
    -H "Content-Type: application/json" \
    -H "$AUTH_HEADER" \
    -d '{
        "github_repository_url": "https://github.com/svylabs/predify",
        "submission_id": "test-submission-id"
    }'

# Test /api/analyze
curl -X POST "$BASE_URL/api/analyze" \
    -H "Content-Type: application/json" \
    -H "$AUTH_HEADER" \
    -d '{
        "submission_id": "test-submission-id"
    }'

# Test /api/analyze_project
curl -X POST "$BASE_URL/api/analyze_project" \
    -H "Content-Type: application/json" \
    -H "$AUTH_HEADER" \
    -d '{
        "submission_id": "test-submission-id"
    }'

# Test /api/analyze_actors
curl -X POST "$BASE_URL/api/analyze_actors" \
    -H "Content-Type: application/json" \
    -H "$AUTH_HEADER" \
    -d '{
        "submission_id": "test-submission-id"
    }'

# Test /api/analyze_deployment
curl -X POST "$BASE_URL/api/analyze_deployment" \
    -H "Content-Type: application/json" \
    -H "$AUTH_HEADER" \
    -d '{
        "submission_id": "test-submission-id"
    }'