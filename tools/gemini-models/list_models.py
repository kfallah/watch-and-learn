"""List Gemini models available for generateContent."""

import os
import sys

import google.generativeai as genai


def main() -> int:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY is not set.")
        return 1

    genai.configure(api_key=api_key)

    for model in genai.list_models():
        if "generateContent" in model.supported_generation_methods:
            print(model.name)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
