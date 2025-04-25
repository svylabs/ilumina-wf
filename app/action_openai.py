# action_openai.py
import os
from google import genai

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

def ask_openai(prompt: str, task: str = "generate") -> str:
    try:
        # Dynamically select the model based on the task
        if task == "generate":
            model = client.models.get('gemini-2.0-flash')
        elif task == "reason":
            model = client.models.get('gemini-1.5-pro')
        elif task == "understand":
            model = client.models.get('gemini-1.5-flash')
        else:
            raise ValueError(f"Unknown task: {task}")

        # Generate content
        response = model.generate_content(
            contents=prompt,
            # generation_config={
            #     "temperature": 0.7,
            #     "response_mime_type": "text/plain"
            # }
        )
        
        # Return the plain text response
        if not response.text:
            raise ValueError("Empty response from Gemini API")
        return response.text
    
    except Exception as e:
        return f"Error: {str(e)}"