FROM python:3.13-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[example]"

COPY examples/api.py ./api.py

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
