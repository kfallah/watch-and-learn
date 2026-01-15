# Gemini Model Lister

This script lists models that support `generateContent` for your API key.

## Run inside the worker container (recommended)

```bash
docker compose cp tools/gemini-models/list_models.py worker-1:/app/list_models.py
docker compose exec worker-1 python /app/list_models.py
```

## Run on host (if you already have deps)

```bash
python tools/gemini-models/list_models.py
```

Make sure `GEMINI_API_KEY` is set in your environment.
