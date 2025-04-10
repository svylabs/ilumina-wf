from functools import wraps
from flask import request, jsonify
import os

SECRET_PASSWORD = os.getenv("API_SECRET", "my_secure_password")

def authenticate(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get("Authorization")
        if not auth_header or auth_header != f"Bearer {SECRET_PASSWORD}":
            return jsonify({"error": "Unauthorized access"}), 401
        return f(*args, **kwargs)
    return decorated_function
