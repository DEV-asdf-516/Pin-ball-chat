FROM python:3.12-slim
WORKDIR /app
COPY apps/api/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY apps/api/src /app/src
COPY libs /app/libs
ENV PYTHONPATH=/app/src:/app/libs
CMD ["uvicorn", "server.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
