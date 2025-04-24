import google.generativeai as genai
from dotenv import load_dotenv
import os

load_dotenv()

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

def ask_openai(user_input, response_type=None, task="generate"):
    try:
        # Create model instance
        model = genai.GenerativeModel("gemini-1.5-pro")
        # model = genai.GenerativeModel("gemini-1.5-flash") # For Gemini 1.5 Flash is for Speed

        # Start a chat session
        chat = model.start_chat(history=[])

        # Send a message
        response = chat.send_message(
            user_input,
            generation_config={
                "temperature": 0.7,
                "max_output_tokens": 2048
            }
        )

        # Extract response text
        if response.text:
            if response_type == "text":
                return response.text
            else:
                return (response_type, response.text)
        else:
            raise ValueError("No response content received from Gemini API")

    except Exception as e:
        print(f"Error in ask_openai: {str(e)}")
        raise
