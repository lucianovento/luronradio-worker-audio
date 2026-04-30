"""
RunPod Serverless handler para Luron Radio worker-audio.

Stack: F5-TTS + modelo F5-Spanish (jpgallegoar/F5-Spanish, 700h de audio en español).

Acciones:
  - infer  : sintetizar texto con la voz `voice_slug` (zero-shot via reference)
  - warmup : pre-carga modelo en VRAM

Layout esperado en el volumen montado en /runpod-volume:

  /runpod-volume/
  ├── base_models/F5-Spanish/
  │   ├── model_1250000.safetensors   (1.3 GB, modelo entrenado en español)
  │   └── vocab.txt
  └── reference_voices/
      ├── sasha-v1.wav    (~12 seg, mono 32kHz)
      ├── sasha-v1.txt    (transcripción exacta del wav)
      ├── denisse-v1.wav
      └── denisse-v1.txt

Request:
  {"input": {"action": "infer", "voice_slug": "sasha-v1", "text": "...", "speed": 1.0}}

Response:
  {"output": {"audio_base64": "...", "duration_sec": 8.9, "voice_used": "sasha-v1", "model_version": "f5-spanish-v1"}}
"""
import base64
import io
import os
import sys
import time
import traceback

import runpod

VOLUME_PATH = os.environ.get("VOLUME_PATH", "/runpod-volume")
F5_MODEL_PATH = os.environ.get("F5_MODEL_PATH", f"{VOLUME_PATH}/base_models/F5-Spanish/model_1250000.safetensors")
F5_VOCAB_PATH = os.environ.get("F5_VOCAB_PATH", f"{VOLUME_PATH}/base_models/F5-Spanish/vocab.txt")
REFERENCE_PATH = os.environ.get("REFERENCE_PATH", f"{VOLUME_PATH}/reference_voices")
F5_MODEL_NAME = os.environ.get("F5_MODEL_NAME", "F5TTS_Base")

# Singleton del modelo (se carga una sola vez por worker, persiste mientras esté warm)
_F5_INSTANCE = None


def _load_model():
    global _F5_INSTANCE
    if _F5_INSTANCE is not None:
        return _F5_INSTANCE

    print(f"[load] cargando F5-TTS ({F5_MODEL_NAME}) desde {F5_MODEL_PATH}")
    t0 = time.time()
    from f5_tts.api import F5TTS

    _F5_INSTANCE = F5TTS(
        model=F5_MODEL_NAME,
        ckpt_file=F5_MODEL_PATH,
        vocab_file=F5_VOCAB_PATH,
    )
    print(f"[load] OK en {time.time() - t0:.1f}s")
    return _F5_INSTANCE


def _wav_bytes_to_mp3(wav_bytes, sr):
    """Convierte WAV (numpy array) a MP3 bytes."""
    import soundfile as sf
    from pydub import AudioSegment

    wav_buf = io.BytesIO()
    sf.write(wav_buf, wav_bytes, sr, format="WAV")
    wav_buf.seek(0)

    audio = AudioSegment.from_wav(wav_buf)
    mp3_buf = io.BytesIO()
    audio.export(mp3_buf, format="mp3", bitrate="128k")
    return mp3_buf.getvalue()


def run_infer(voice_slug, text, speed=1.0, output_format="mp3", remove_silence=True):
    f5 = _load_model()

    ref_audio = os.path.join(REFERENCE_PATH, f"{voice_slug}.wav")
    ref_text_path = os.path.join(REFERENCE_PATH, f"{voice_slug}.txt")

    if not os.path.exists(ref_audio):
        return {"error": f"reference audio not found: {ref_audio}"}
    if not os.path.exists(ref_text_path):
        return {"error": f"reference transcript not found: {ref_text_path}"}

    ref_text = open(ref_text_path).read().strip()

    print(f"[infer] voice={voice_slug} text_len={len(text)} speed={speed}")
    t0 = time.time()
    wav, sr, _ = f5.infer(
        ref_file=ref_audio,
        ref_text=ref_text,
        gen_text=text,
        speed=speed,
        remove_silence=remove_silence,
    )
    elapsed = time.time() - t0
    duration = len(wav) / sr
    print(f"[infer] generado en {elapsed:.1f}s ({duration:.1f}s de audio, RTF={elapsed/duration:.2f}x)")

    if output_format == "mp3":
        audio_bytes = _wav_bytes_to_mp3(wav, sr)
        mime = "audio/mpeg"
    else:
        import soundfile as sf
        buf = io.BytesIO()
        sf.write(buf, wav, sr, format="WAV")
        audio_bytes = buf.getvalue()
        mime = "audio/wav"

    return {
        "audio_base64": base64.b64encode(audio_bytes).decode("utf-8"),
        "duration_sec": round(duration, 2),
        "render_time_sec": round(elapsed, 2),
        "voice_used": voice_slug,
        "model_version": "f5-spanish-1250000",
        "format": output_format,
        "mime": mime,
        "sample_rate": sr,
    }


def handler(event):
    try:
        inp = event.get("input", {})
        action = inp.get("action", "infer")

        if action == "warmup":
            _load_model()
            return {"status": "warm", "model": F5_MODEL_NAME, "ckpt": F5_MODEL_PATH}

        elif action == "infer":
            return run_infer(
                voice_slug=inp["voice_slug"],
                text=inp["text"],
                speed=float(inp.get("speed", 1.0)),
                output_format=inp.get("format", "mp3"),
                remove_silence=bool(inp.get("remove_silence", True)),
            )

        elif action == "list_voices":
            voices = []
            if os.path.exists(REFERENCE_PATH):
                for f in sorted(os.listdir(REFERENCE_PATH)):
                    if f.endswith(".wav"):
                        slug = f[:-4]
                        if os.path.exists(os.path.join(REFERENCE_PATH, f"{slug}.txt")):
                            voices.append(slug)
            return {"voices": voices, "reference_path": REFERENCE_PATH}

        else:
            return {"error": f"Unknown action: {action}"}

    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        return {"error": str(e), "trace": traceback.format_exc()}


runpod.serverless.start({"handler": handler})
