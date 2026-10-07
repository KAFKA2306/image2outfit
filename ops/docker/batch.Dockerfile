FROM python:3.11-slim

WORKDIR /workspace

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install --no-cache-dir .

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

CMD ["python", "tools/manage.py", "batch", "status", "--manifest", "config/batch/tracked-requests.json"]
