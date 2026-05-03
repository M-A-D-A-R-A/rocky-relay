# Iteration: Mac Microphone Input

Date: 2026-05-03

## Goal

Move from audio-file benchmarks to the first live Mac microphone loop:

```text
Mac mic -> captured WAV -> STT -> LLM -> Rocky/persona transform -> TTS -> response WAV
```

## Implementation

Added `rocky-relay-record-turn`, a Python CLI that:

- records a fixed-duration WAV through `ffmpeg` AVFoundation,
- saves the input under `captures/`,
- runs the existing `run_audio_turn(...)` pipeline,
- writes the response under `outputs/`,
- appends live records to `logs/conversations/recorded_turns.jsonl`,
- optionally plays the response with `--play`.

## Why Fixed Duration First

Fixed duration is a simpler benchmark harness than push-to-talk:

- it avoids button/key-release handling in the first pass,
- it makes capture time explicit,
- it lets us compare file-based latency against live capture latency,
- it still maps cleanly to the later Pi client.

## Commands

List Mac audio devices:

```bash
rocky-relay-record-turn --list-devices
```

Record only:

```bash
rocky-relay-record-turn \
  --duration 3 \
  --device ":1" \
  --record-only
```

Full fast path:

```bash
rocky-relay-record-turn \
  --duration 3 \
  --device ":1" \
  --stt smallest_ai \
  --llm ollama \
  --persona rocky_say \
  --tts smallest_ai \
  --play \
  --json
```

One-recording benchmark for both hosted and local STT:

```bash
rocky-relay-benchmark-live \
  --duration 3 \
  --device ":1" \
  --stt smallest_ai \
  --stt whisper_cpp \
  --llm ollama \
  --persona rocky_say \
  --tts smallest_ai
```

## Current Observation

The Codex sandbox could run the command and found `ffmpeg`, but AVFoundation did
not expose audio devices in this session. The expected local fix is granting
microphone access to the terminal/Codex host app in macOS System Settings.

## Next

After one successful fixed-duration live run, add:

- benchmark appending for live mic rows,
- press-and-hold or enter-to-stop capture,
- local server `/audio` endpoint so the Mac command mirrors the future Pi client.

Playback-start timing has now been added behind `--play` as
`playback_startup_ms` and `trigger_to_first_audible_ms`.
