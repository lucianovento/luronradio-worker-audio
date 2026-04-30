# RunPod Serverless worker para Luron Radio audio (F5-TTS + español)
# Base: PyTorch 2.5 + CUDA 12.1 (mismo que el Pod donde validamos)
FROM pytorch/pytorch:2.5.1-cuda12.1-cudnn9-runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HUB_DISABLE_TELEMETRY=1

# Sistema: ffmpeg para audio, libsndfile para soundfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Cache de pip — instalar requirements primero para aprovechar layer cache
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Código del worker
COPY handler.py ./

# Pre-bajar el vocoder Vocos (el modelo F5 lo necesita; está en HF, ~70 MB)
# Esto evita el cold start de bajarlo en el primer request.
RUN python -c "from cached_path import cached_path; cached_path('hf://charactr/vocos-mel-24khz/pytorch_model.bin'); cached_path('hf://charactr/vocos-mel-24khz/config.yaml')" || echo "vocos pre-cache fallo, se bajará en runtime"

# RunPod entry point
CMD ["python", "-u", "handler.py"]
