import os

async def get_yandex_response(messages):
    from yandex_cloud_ml_sdk import AsyncYCloudML

    sdk = AsyncYCloudML(
        folder_id=os.getenv("YANDEX_FOLDER_ID"), auth=os.getenv("YANDEX_GPT_API_KEY")
    )

    model = sdk.models.completions("yandexgpt")
    result = await model.configure(temperature=0.3).run(messages)
    response = result.alternatives[0].text

    return response


async def get_openrouter_response(messages):
    headers = {
        "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
        "Content-Type": "application/json",
    }

    model = "qwen/qwen-2-7b-instruct:free"

    data = {"model": model, "messages": messages, "temperature": 0.3}

    import requests
    import json

    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers=headers,
        data=json.dumps(data),
    )
    result = response.json()

    response_text = result["choices"][0]["message"]["content"]

    return response_text
