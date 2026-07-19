# Ollama CLI 0.32.0 is copied in so register_model.py can use OLLAMA_HOST.
FROM ollama/ollama:0.32.0 AS ollama-client

# Checked 2026-07-18: PyTorch's official Docker Hub tags list this as the
# latest stable CUDA runtime image (PyTorch 2.11.0, CUDA 13.0, cuDNN 9).
FROM pytorch/pytorch:2.11.0-cuda13.0-cudnn9-runtime

WORKDIR /workspace

COPY trainer/worker/requirements-worker.txt /tmp/requirements-worker.txt
RUN pip install --no-cache-dir -r /tmp/requirements-worker.txt \
    && apt-get update \
    && apt-get install --yes --no-install-recommends build-essential cmake git \
    && git clone --depth 1 https://github.com/ggerganov/llama.cpp.git /opt/llama.cpp \
    && cmake -S /opt/llama.cpp -B /opt/llama.cpp/build \
    && cmake --build /opt/llama.cpp/build --target llama-quantize -j"$(nproc)" \
    && ln -s /opt/llama.cpp/build/bin/llama-quantize /usr/local/bin/llama-quantize \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ollama-client /bin/ollama /usr/local/bin/ollama
COPY trainer/api trainer/jobs trainer/recipes trainer/worker /workspace/trainer/
COPY libs /workspace/libs
ENV PYTHONPATH=/workspace/libs

CMD ["python", "trainer/worker/runner.py"]
