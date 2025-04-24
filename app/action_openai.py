# action_openai.py
from dotenv import load_dotenv
import os
import google.generativeai as genai

load_dotenv()

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

def ask_openai(prompt: str) -> str:
    try:
        # Get the client and specify the model
        client = genai.Client()
        model = client.models.get('gemini-2.0-flash')

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