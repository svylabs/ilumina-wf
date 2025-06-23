from openai import OpenAI
from dotenv import load_dotenv
import os

client = OpenAI(api_key=os.getenv("GEMINI_API_KEY"), base_url="https://generativelanguage.googleapis.com/v1beta/openai/")

def ask_openai(user_input, type, task="generate", conversations=None, options=None):
    # Add user message
    if conversations is None:
        conversations = []
    conversations.append({"role": "user", "content": user_input})
    
    """ model = "gpt-4o"
    if task == "reason":
        model = "o3-mini"
    elif task == "understand":
        model = "o3-mini" """
    #model = "gemini-2.0-flash"
    # model = os.getenv("MODEL", "gemini-2.0-flash")

    # Determine model based on plan (default to free if not specified)
    plan = options.get("plan", "free") if options else "free"

    if plan == "paid":
        model = os.getenv("PAID_MODEL", "gemini-2.0-flash")
        # model = os.getenv("PAID_MODEL", "gemini-2.0-pro")
    else:
        model = os.getenv("FREE_MODEL", "gemini-2.0-flash")

    # Get response
    response = client.beta.chat.completions.parse(model=model,
        messages=conversations,
        response_format=type,
        timeout=120)
        #print(response)
    value = response.choices[0].message.parsed
        #conversation.append({"role": "assistant", "content": contract})
    return (type, value)


