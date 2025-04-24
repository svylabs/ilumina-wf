import google.generativeai as genai
from dotenv import load_dotenv
import os

load_dotenv()

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

def ask_openai(user_input, type, task="generate"):
    # Placeholder for future token checking or summarization logic
    """
    if count_tokens(conversation) > MAX_TOKENS:
        print("🧠 Summarizing conversation...")
        summary = summarize_conversation(user_input)
        conversation.clear()
        conversation.extend(summary)
    """

    # Model selection placeholder (for future multi-model support)
    """
    model_name = "gemini-pro"
    if task == "reason":
        model_name = "some-other-model"
    elif task == "understand":
        model_name = "some-other-model"
    """

    # Create model instance
    model = genai.GenerativeModel("gemini-pro")

    # Start chat session
    chat = model.start_chat(history=[])

    # Send user message
    response = chat.send_message(
        user_input,
        generation_config={
            "temperature": 0.7,
            "max_output_tokens": 2048
        }
    )

    # Extract response text
    value = response.text
    return (type, value)
