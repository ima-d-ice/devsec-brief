import os
import requests
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

headers = {
    "Authorization": f"Bearer {GROQ_API_KEY}",
    "Content-Type": "application/json"
}

# The model specified in evaluate.py
data = {
    "model": "openai/gpt-oss-120b",
    "messages": [{"role": "user", "content": "hi"}],
    "max_tokens": 10
}

response = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=data)

if response.status_code == 200:
    h = response.headers
    print("=== Groq API Rate Limits for openai/gpt-oss-120b ===")
    print(f"Requests Remaining (RPM): {h.get('x-ratelimit-remaining-requests', 'N/A')}")
    print(f"Tokens Remaining (TPM):   {h.get('x-ratelimit-remaining-tokens', 'N/A')}")
    print(f"Tokens Limit (TPD):       {h.get('x-ratelimit-limit-tokens', 'N/A')}")
else:
    print(f"Error: {response.status_code} - {response.text}")
