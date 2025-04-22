from openai import OpenAI
from dotenv import load_dotenv
import os

load_dotenv()

client = OpenAI(
    api_key=os.getenv("GEMINI_API_KEY"),
    base_url="https://generativelanguage.googleapis.com/v1beta/models/"
)

def ask_openai(user_input, response_type=None, task="generate"):
    try:
        # For Gemini API, we don't use response_format parameter
        model = "gemini-pro"  # or "gemini-1.5-flash" depending on your needs
        
        # Create the prompt structure for Gemini
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": user_input}],
            temperature=0.7,
            max_tokens=2048
        )
        
        # Extract the content from the response
        if response.choices and len(response.choices) > 0:
            content = response.choices[0].message.content
            if response_type == "text":
                return content
            else:
                return (response_type, content)
        else:
            raise ValueError("No response content received from Gemini API")
            
    except Exception as e:
        print(f"Error in ask_openai: {str(e)}")
        raise