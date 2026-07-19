FROM python:3.12-slim

WORKDIR /workspace

COPY trainer/api/requirements-api.txt /tmp/requirements-api.txt
RUN pip install --no-cache-dir -r /tmp/requirements-api.txt

COPY trainer/api /workspace/trainer/api
COPY libs /workspace/libs
ENV PYTHONPATH=/workspace/libs

CMD ["uvicorn", "trainer.api.main:app", "--host", "0.0.0.0", "--port", "8090"]
