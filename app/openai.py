from openai import OpenAI
from dotenv import load_dotenv
import os

client = OpenAI(api_key=os.getenv("GEMINI_API_KEY"), base_url="https://generativelanguage.googleapis.com/v1beta/openai/")

def ask_openai(user_input, type, task="generate", conversations=None):
    # Add user message
    if conversations is None:
        conversations = []
    conversations.append({"role": "user", "content": user_input})

    # Check token limit
    """ if count_tokens(conversation) > MAX_TOKENS:
        print("🧠 Summarizing conversation...")
        summary = summarize_conversation(user_input)
        # Reset with summary only
        conversation.clear()
        conversation.extend(summary)
 """
    
    """ model = "gpt-4o"
    if task == "reason":
        model = "o3-mini"
    elif task == "understand":
        model = "o3-mini" """
    model = "gemini-2.0-flash"

    # Get response
    response = client.beta.chat.completions.parse(model=model,
        messages=conversations,
        response_format=type,
        timeout=30)
        #print(response)
    value = response.choices[0].message.parsed
        #conversation.append({"role": "assistant", "content": contract})
    return (type, value)


