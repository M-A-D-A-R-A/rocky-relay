# Benchmarks

Latency measurements for Rocky Relay. All values are from local development
runs unless otherwise noted.

## Environment

- Date: 2026-05-03
- Host: Mac
- LLM: Ollama `llama3.2:1b`
- Persona: `rocky_say` unless otherwise noted
- Output format: WAV

## Current Baselines

| Scenario | Backend | LLM | Persona | TTS | Total | Notes |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Tiny echo -> Rocky cloned TTS | `rocky_xtts_cli` | 0.01ms | 0.26ms | 6194.98ms | n/a | Old subprocess wrapper path |
| Tiny echo -> Rocky cloned TTS | `rocky_xtts` | 0.00ms | 0.30ms | 4120.66ms | n/a | Direct Rocky HTTP server path |
| Ollama -> Rocky cloned TTS | `rocky_xtts` | 1769.39ms | 120.58ms | 4580.51ms | n/a | Short response |
| Tiny echo -> YourTTS | `rocky_yourtts` | 0.01ms | 0.32ms | 26557.55ms | n/a | Too slow in current setup |
| Ollama -> macOS speech | `macos_say` | 383.99ms | 129.03ms | 794.37ms | n/a | Real speech, not cloned Rocky |

## Current Comparison

Full audio-file pipeline:

| Pipeline | STT | LLM | TTS | Total |
| --- | ---: | ---: | ---: | ---: |
| Smallest STT -> Ollama -> Smallest TTS | 359.86ms | 624.40ms | 1001.08ms | 2043.52ms |
| whisper.cpp -> Ollama -> macOS TTS | 2521.38ms | 763.79ms | 1059.66ms | 4440.79ms |
| whisper.cpp -> Ollama -> silent TTS | 2479.09ms | 563.09ms | 3.95ms | 3189.74ms |
| Smallest STT isolated-ish | 256-333ms | ~0ms | ~5ms | 338.27ms |
| whisper.cpp STT isolated-ish | 1579.40ms | ~0ms | ~3ms | 1583.03ms |

TTS-only comparison:

| TTS Backend | Total |
| --- | ---: |
| Smallest AI | 516.07ms |
| macOS say | 2746.09ms |
| Rocky XTTS direct | 4135.97ms |
| Rocky XTTS CLI | 4720.85ms |
| Rocky YourTTS | 10184.11ms |

Current fastest realistic path:

```text
Smallest STT -> Ollama llama3.2:1b -> Rocky text transform -> Smallest TTS
```

This lands around 2.0s full audio-file-to-audio-file in the current benchmark,
with earlier logs showing a best observed full Smallest/Ollama path around 1.26s.
`whisper.cpp` works as an offline fallback, but CPU mode currently adds roughly
1.2-2.2s over Smallest STT on the short Rocky test WAV.

## Smallest AI Test Plan

Set the API key in your shell:

```bash
export SMALLEST_API_KEY="..."
```

Optional: create a short clone sample from the local Rocky reference audio:

```bash
ffmpeg \
  -y \
  -i ../rocky-pi/rocky/rocky_training_audio_scrubbed.wav \
  -t 12 \
  -ac 1 \
  -ar 24000 \
  outputs/rocky-smallest-sample.wav
```

Create a Smallest AI voice clone:

```bash
rocky-relay-smallest-clone \
  --file outputs/rocky-smallest-sample.wav \
  --display-name rocky-relay-test \
  --language en \
  --accent general
```

Put the returned `data.voiceId` into `config.json` as `smallest_voice_id`.

Run a TTS-only-ish benchmark using `echo` LLM:

```bash
rocky-relay-benchmark-tts \
  --text "hello" \
  --llm echo \
  --persona rocky_basic \
  --tts smallest_ai
```

Run a full typed turn:

```bash
rocky-relay-benchmark-tts \
  --text "Reply in five words: hello friend." \
  --llm ollama \
  --persona rocky_say \
  --tts smallest_ai
```

The benchmark command appends rows to this file.

## STT Test Plan

Use a real WAV file for STT. Good options:

- A short recorded microphone WAV.
- A previous TTS output from `outputs/`.
- `outputs/rocky-direct-test.wav` if present from the Rocky clone smoke test.

Optional macOS helper:

```bash
rocky-relay-make-sample-audio \
  "hello friend" \
  --output samples/hello-friend.wav
```

If this helper produces an empty WAV in a non-interactive shell, use a recorded
WAV or previous TTS output instead.

Run an STT-isolated benchmark. This uses `echo` for LLM and `silent` for TTS so
the useful number is `STT`:

```bash
rocky-relay-benchmark-stt \
  --audio outputs/rocky-direct-test.wav \
  --stt smallest_ai \
  --llm echo \
  --persona none \
  --tts silent
```

Run an end-to-end audio-file benchmark:

```bash
rocky-relay-benchmark-stt \
  --audio outputs/rocky-direct-test.wav \
  --stt smallest_ai \
  --llm ollama \
  --persona rocky_say \
  --tts smallest_ai
```

## Result Template

TTS:

| Date | Scenario | Backend | LLM | Persona | TTS | Total | Audio path | Notes |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| 2026-05-03 |  | `smallest_ai` |  |  |  |  | `outputs/...wav` |  |
| 2026-05-03 | `hello` | `smallest_ai` | 0.01 | 0.55 | 570.46 | n/a | `/Users/nandoriy/Documents/aiprojects/voice-lab/rocky-relay/outputs/9438e54a0dd2.wav` | benchmark command |
| 2026-05-03 | `Reply in five words: hello friend.` | `smallest_ai` | 1851.86 | 82.07 | 548.74 | n/a | `/Users/nandoriy/Documents/aiprojects/voice-lab/rocky-relay/outputs/84fa0c438be8.wav` | benchmark command |
| 2026-05-03 | `hello` | `smallest_ai` | 0.0 | 0.29 | 533.91 | n/a | `/Users/nandoriy/Documents/aiprojects/voice-lab/rocky-relay/outputs/6ba5f9c57e52.wav` | benchmark command |
| 2026-05-03 | `hello` | `macos_say` | 0.0 | 0.22 | 2745.84 | 2746.09 | `/Users/nandoriy/Documents/aiprojects/voice-lab/rocky-relay/outputs/974da7977a9d.wav` | benchmark command |
| 2026-05-03 | `hello` | `smallest_ai` | 0.01 | 0.09 | 515.91 | 516.07 | `/Users/nandoriy/Documents/aiprojects/voice-lab/rocky-relay/outputs/a8571090e7a2.wav` | benchmark command |
| 2026-05-03 | `hello` | `rocky_xtts` | 0.01 | 0.15 | 4135.78 | 4135.97 | `/Users/nandoriy/Documents/aiprojects/voice-lab/rocky-relay/outputs/ce2d0d59dfca.wav` | benchmark command |
| 2026-05-03 | `Reply in five words: hello friend.` | `macos_say` | 1848.64 | 87.85 | 1599.52 | 3536.31 | `/Users/nandoriy/Documents/aiprojects/voice-lab/rocky-relay/outputs/727f0c120799.wav` | benchmark command |
| 2026-05-03 | `Reply in five words: hello friend.` | `smallest_ai` | 365.03 | 105.32 | 735.93 | 1206.34 | `/Users/nandoriy/Documents/aiprojects/voice-lab/rocky-relay/outputs/150cc0f19919.wav` | benchmark command |
| 2026-05-03 | `Reply in five words: hello friend.` | `rocky_xtts` | 246.79 | 47.79 | 4594.13 | 4888.76 | `/Users/nandoriy/Documents/aiprojects/voice-lab/rocky-relay/outputs/a2191f559be9.wav` | benchmark command |
| 2026-05-03 | `hello` | `rocky_xtts_cli` | 0.0 | 0.24 | 4720.57 | 4720.85 | `/Users/nandoriy/Documents/aiprojects/voice-lab/rocky-relay/outputs/453481b18804.wav` | benchmark command |
| 2026-05-03 | `hello` | `rocky_yourtts` | 0.01 | 0.09 | 10183.97 | 10184.11 | `/Users/nandoriy/Documents/aiprojects/voice-lab/rocky-relay/outputs/edfb14154bdc.wav` | benchmark command |

STT / Audio Turn:

| Date | Audio | STT Backend | STT | LLM | Persona | TTS | Total | Transcript | Audio path | Notes |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |
| 2026-05-03 | `outputs/rocky-direct-test.wav` | `smallest_ai` | 333.39 | 0.01 | 0.15 | 4.67 | 338.27 | `Hello friend!` | `/Users/nandoriy/Documents/aiprojects/voice-lab/rocky-relay/outputs/adfce8251ffa.wav` | benchmark command |
| 2026-05-03 | `outputs/rocky-direct-test.wav` | `smallest_ai` | 256.29 | 2083.98 | 71.2 | 1076.78 | 3488.56 | `Hello friend!` | `/Users/nandoriy/Documents/aiprojects/voice-lab/rocky-relay/outputs/fed9151ccf17.wav` | benchmark command |
| 2026-05-03 | `outputs/rocky-direct-test.wav` | `whisper_cpp` | 1579.4 | 0.03 | 0.19 | 3.3 | 1583.03 | `Hello, friend!` | `/Users/nandoriy/Documents/aiprojects/voice-lab/rocky-relay/outputs/066ec54f9b4d.wav` | benchmark command |
| 2026-05-03 | `outputs/rocky-direct-test.wav` | `whisper_cpp` | 2479.09 | 563.09 | 143.48 | 3.95 | 3189.74 | `Hello, friend!` | `/Users/nandoriy/Documents/aiprojects/voice-lab/rocky-relay/outputs/62b900f27905.wav` | benchmark command |
| 2026-05-03 | `outputs/rocky-direct-test.wav` | `whisper_cpp` | 2521.38 | 763.79 | 95.83 | 1059.66 | 4440.79 | `Hello, friend!` | `/Users/nandoriy/Documents/aiprojects/voice-lab/rocky-relay/outputs/b61c35e1e466.wav` | benchmark command |
| 2026-05-03 | `outputs/rocky-direct-test.wav` | `smallest_ai` | 359.86 | 624.4 | 58.08 | 1001.08 | 2043.52 | `Hello friend!` | `/Users/nandoriy/Documents/aiprojects/voice-lab/rocky-relay/outputs/165430e9faa1.wav` | benchmark command |
