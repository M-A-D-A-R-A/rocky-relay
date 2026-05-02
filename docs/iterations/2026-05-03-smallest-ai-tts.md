# Iteration: Smallest AI TTS Backend

Date: 2026-05-03

## Goal

Evaluate a third-party low-latency TTS provider as a faster alternative to local
Rocky XTTS cloned voice generation.

## Why

Local Rocky XTTS works, but current warm latency is still too high for a natural
voice assistant loop:

- Tiny Rocky XTTS direct HTTP test: about 4.1s TTS.
- Short Ollama + Rocky XTTS turn: about 4.6s TTS, plus LLM latency.
- YourTTS path in the local Rocky script was slower in our test.

For the Pi 4 target, cloned TTS should probably stay off-device. A hosted TTS
provider lets us compare local quality mode against a network-backed low-latency
mode without changing the client/server architecture.

## Provider Choice

Start with Smallest AI directly instead of Bolna.

Reasoning:

- Smallest AI is a direct TTS/STT provider, so it fits our existing
  `TTSBackend` interface cleanly.
- Bolna is more of a full voice-agent orchestration layer. That may be useful
  later, but it adds abstraction before we have baseline TTS numbers.
- Direct integration gives us clearer latency measurements.

## Implemented

Added `smallest_ai` as a TTS backend.
Added `rocky-relay-smallest-clone` as a helper for creating an instant voice
clone from a short local audio sample.

Configuration:

```json
{
  "smallest_api_key_env": "SMALLEST_API_KEY",
  "smallest_tts_url": "https://api.smallest.ai/waves/v1/lightning-v3.1/get_speech",
  "smallest_voice_id": "magnus",
  "smallest_sample_rate": 24000,
  "smallest_speed": 1.0,
  "smallest_language": "en",
  "smallest_output_format": "wav"
}
```

Runtime command:

```bash
export SMALLEST_API_KEY="..."

rocky-relay-turn \
  "Reply in five words: hello friend." \
  --llm ollama \
  --persona rocky_say \
  --tts smallest_ai \
  --json
```

Voice clone helper:

```bash
rocky-relay-smallest-clone \
  --file outputs/rocky-smallest-sample.wav \
  --display-name rocky-relay-test \
  --language en \
  --accent general
```

Use the returned `data.voiceId` as `smallest_voice_id` in `config.json`.

## References

- Smallest AI Lightning Text-to-Speech docs:
  https://docs.smallest.ai/waves/documentation/text-to-speech-lightning/overview
- Smallest AI voice cloning API docs:
  https://docs.smallest.ai/waves/api-reference/voice-cloning/create
- Bolna open-source voice agent framework:
  https://github.com/bolna-ai/bolna

## Open Questions

- What `voice_id` should we use for the Rocky-style clone after creating/uploading
  a voice in Smallest AI?
- Is sync TTS fast enough, or do we need their streaming endpoint for
  trigger-to-first-audio?
- Does hosted TTS quality feel close enough to Rocky, or should it be a separate
  "fast voice" mode?
