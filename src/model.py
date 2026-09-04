import os

import requests


def ask_model(prompt):
    api_key = os.environ.get("OPENROUTER_API_KEY")

    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. "
            "Set it in your terminal before asking the AI."
        )

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "openrouter/free",
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
            },
            timeout=30,
        )

        response.raise_for_status()

    except requests.exceptions.Timeout:
        raise RuntimeError(
            "The AI request timed out. Please try again."
        )

    except requests.exceptions.RequestException as error:
        raise RuntimeError(
            f"The AI request failed: {error}"
        )

    data = response.json()

    return data["choices"][0]["message"]["content"]