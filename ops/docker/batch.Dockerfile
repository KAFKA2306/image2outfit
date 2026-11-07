FROM python:3.11-slim

WORKDIR /workspace

RUN python -m pip install --no-cache-dir Pillow==12.3.0

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

CMD ["python", "tools/manage.py", "batch", "status", "--manifest", "config/batch/tracked-requests.json"]
