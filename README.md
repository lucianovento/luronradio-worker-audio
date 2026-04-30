# Luron Radio — Worker de Audio (RunPod Serverless)

Worker TTS con voice cloning en español para Luron Radio.

**Stack:** [F5-TTS](https://github.com/SWivid/F5-TTS) + modelo [F5-Spanish](https://huggingface.co/jpgallegoar/F5-Spanish) (700 horas de audio en español).

**Calidad:** zero-shot con 10-15 seg de referencia, RTF (real-time factor) ~0.5x en RTX 4090 (genera audio el doble de rápido que su duración).

---

## Lo que necesitás antes

1. **Cuenta en RunPod** (ya tenés).
2. **Network Volume** `luronradio-voice` (20 GB, en EU-RO-1) — ya creado.
3. **Modelo F5-Spanish + sample de Sasha** ya están en el volumen (los dejó el setup del Pod). Layout:
   ```
   /runpod-volume/
   ├── base_models/F5-Spanish/
   │   ├── model_1250000.safetensors
   │   └── vocab.txt
   └── reference_voices/
       ├── sasha-v1.wav
       └── sasha-v1.txt
   ```
4. **Tu llave pública SSH** ya está en RunPod Settings (lo hicimos antes).

---

## Crear el endpoint Serverless (5 clicks)

1. **RunPod → Serverless → New Endpoint**.
2. **Source**:
   - Tab: **GitHub**
   - Repo: `lucianovento/luronradio-worker-audio`
   - Branch: `main`
3. **Configuration**:
   | Campo | Valor |
   |---|---|
   | GPU | **RTX 4090** (1x) |
   | Container disk | `20 GB` |
   | Active workers | `0` (idle) |
   | Max workers | `2` |
   | Idle timeout | `30` segundos |
   | Execution timeout | `300` segundos |
   | Datacenter filter | **EU-RO-1** (mismo que el volumen) |
4. **Network Volume**: dropdown → seleccionar `luronradio-voice`.
   El path de mount es `/runpod-volume` por convención (el handler ya lee de ahí).
5. **Deploy**.

El primer build del Docker image tarda ~8-12 min. Mientras builda podés mirar logs en la pestaña "Builds".

Cuando esté **Ready**, anotá:
- **Endpoint URL** (ej. `https://api.runpod.ai/v2/abc123xyz`)
- **API Key** (RunPod → Settings → API Keys → New Key, scope: read+write)

---

## Probar el endpoint

```bash
ENDPOINT="https://api.runpod.ai/v2/abc123xyz"
API_KEY="rpa_xxxxxxxxxxxxx"

# Warmup (carga el modelo en VRAM, ~5 seg)
curl -X POST "$ENDPOINT/runsync" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"input": {"action": "warmup"}}'

# Listar voces disponibles
curl -X POST "$ENDPOINT/runsync" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"input": {"action": "list_voices"}}'

# Inferencia: Sasha leyendo una noticia
curl -X POST "$ENDPOINT/runsync" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "action": "infer",
      "voice_slug": "sasha-v1",
      "text": "Buenas noches, soy Sasha. Estas son las noticias de Luron Radio.",
      "speed": 1.0,
      "format": "mp3"
    }
  }' | jq -r '.output.audio_base64' | base64 -d > test.mp3

# Reproducir
ffplay test.mp3
```

---

## Conectar a luronradio.com (en el droplet)

```bash
ssh claude@147.182.142.140
sudo nano /var/www/luronradio/.env
```

Agregar:
```
RUNPOD_AUDIO_ENDPOINT=https://api.runpod.ai/v2/abc123xyz
RUNPOD_API_KEY=rpa_xxxxxxxxxxxxx
```

Después:
```bash
cd /var/www/luronradio
sudo -u www-data php artisan config:cache
sudo systemctl reload php8.3-fpm
```

Listo. Generar el primer brief desde `/admin/segmentos` → "▶ Generar brief ahora".

---

## API contract

### `infer` — sintetizar audio

**Request:**
```json
{
  "input": {
    "action": "infer",
    "voice_slug": "sasha-v1",
    "text": "Buenas noches, soy Sasha...",
    "speed": 1.0,
    "format": "mp3",
    "remove_silence": true
  }
}
```

| Campo | Default | Descripción |
|---|---|---|
| `voice_slug` | (requerido) | Nombre del archivo en `/runpod-volume/reference_voices/` (sin extensión) |
| `text` | (requerido) | Texto a sintetizar (español). Hasta ~500 palabras por request. |
| `speed` | `1.0` | Velocidad de habla. `0.85`–`1.15` recomendado. |
| `format` | `"mp3"` | `"mp3"` o `"wav"` |
| `remove_silence` | `true` | Quita silencios largos del output |

**Response:**
```json
{
  "output": {
    "audio_base64": "...",
    "duration_sec": 8.9,
    "render_time_sec": 4.4,
    "voice_used": "sasha-v1",
    "model_version": "f5-spanish-1250000",
    "format": "mp3",
    "mime": "audio/mpeg",
    "sample_rate": 24000
  }
}
```

### `list_voices` — listar voces disponibles

```json
{"input": {"action": "list_voices"}}
```

Devuelve `{"voices": ["sasha-v1", ...], "reference_path": "/runpod-volume/reference_voices"}`.

### `warmup` — precargar modelo

```json
{"input": {"action": "warmup"}}
```

Útil para evitar cold start del primer request real. Tarda ~5 seg.

---

## Agregar más voces (Denisse, Irina, etc.)

Para cada nuevo locutor, subir al volumen:
- `/runpod-volume/reference_voices/{slug}.wav` — 10-15 seg de la voz, mono 24kHz, sin música
- `/runpod-volume/reference_voices/{slug}.txt` — transcripción exacta del wav

El handler los detecta automáticamente. No hay que rebuildear el Docker.

Para subir, lo más simple es prender un Pod temporal (mismo volumen montado), hacer scp/upload, y apagarlo. O usar la UI de RunPod si tiene file browser.

---

## Troubleshooting

**Cold start lento (~30-60 seg primer request):**
Normal. El worker carga F5-TTS (~5 seg) y el modelo F5-Spanish (~3 seg) la primera vez. Después responde en ~5 seg por request mientras esté warm.

**`reference audio not found`:**
Verificá que el archivo `.wav` y `.txt` existan en `/runpod-volume/reference_voices/` con el `voice_slug` correcto.

**Audio en otro idioma o ruido:**
Asegurate que `F5_MODEL_NAME=F5TTS_Base` (el modelo F5-Spanish está entrenado sobre esa arquitectura, no `F5TTS_v1_Base`).

**OOM en el GPU:**
RTX 4090 (24 GB) sobra para inferencia. Si pasa, bajar `Max workers` a 1 y verificar que no haya otro proceso usando la VRAM.

---

## Costos estimados

| Operación | Costo |
|---|---|
| Inferencia ~10 seg de audio (RTX 4090) | ~$0.005 |
| Cold start (cargar modelo) | ~$0.003 |
| Volume 20 GB | $1.40/mes |
| 50 briefs/día (2 min total cada uno) | ~$15/mes |

---

## Roadmap

- [ ] Soporte de adapters fine-tuned (entrenar con los 11 min completos para subir calidad de 7.5 → 9+).
- [ ] Endpoint `train` para fine-tunear desde el panel de luronradio.
- [ ] Streaming response para audios largos.
- [ ] Pre-cache de Vocos en el Dockerfile (ya está, pero verificar).
