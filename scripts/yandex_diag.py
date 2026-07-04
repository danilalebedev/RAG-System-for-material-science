import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

folder_id = os.getenv("YANDEX_FOLDER_ID", "").strip()
api_key = os.getenv("YANDEX_API_KEY", "").strip()
base_url = os.getenv("YANDEX_BASE_URL", "https://ai.api.cloud.yandex.net/v1").strip()
env_model = os.getenv("YANDEX_MODEL", "").strip()

print("BASE_URL:", base_url)
print("FOLDER_ID_LEN:", len(folder_id))
print("API_KEY_LEN:", len(api_key))
print("ENV_MODEL:", env_model)

client = OpenAI(
    api_key=api_key,
    project=folder_id,
    base_url=base_url,
)

models = []

if env_model:
    if env_model.startswith("gpt://"):
        models.append(env_model)
    else:
        models.append(f"gpt://{folder_id}/{env_model}")

for model in [
    f"gpt://{folder_id}/aliceai-llm",
    f"gpt://{folder_id}/yandexgpt/latest",
    f"gpt://{folder_id}/yandexgpt/rc",
]:
    if model not in models:
        models.append(model)

for model in models:
    print("\nTRY:", model)
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Ответь одним словом: ok"}],
            max_tokens=20,
            temperature=0,
        )
        print("OK:", response.choices[0].message.content)
    except Exception as e:
        print("ERR:", type(e).__name__)
        print(str(e)[:800])