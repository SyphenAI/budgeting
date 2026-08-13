FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV BUDGET_DATA_DIR=/app/data

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend /app/backend
COPY frontend /app/frontend
COPY brand /app/brand
COPY VERSION /app/VERSION

RUN mkdir -p /app/data

EXPOSE 50100

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "50100"]
