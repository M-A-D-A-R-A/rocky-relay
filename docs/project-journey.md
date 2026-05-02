# Rocky Relay Project Journey

This document captures how Rocky Relay started, what references shaped it, what
we benchmarked, and why the current direction is split into fast hosted TTS and
local Rocky quality mode.

## Starting Point

The project began as a personal low-latency voice assistant experiment:

```text
speech input -> STT -> LLM -> TTS -> spoken reply
```

The long-term hardware target is a Raspberry Pi 4 with:

- Microphone.
- Speaker.
- Push-to-talk button.
- Optional LEDs/status indicators.
- A thin client that sends audio/events to a faster local or hosted server.

The first phase deliberately stayed Mac-first. The reason was simple: benchmark
latency honestly before adding Pi hardware constraints.

## References

### Rocky Voice Clone

Reference:
https://pedsidian.pedramamini.com/Claude/Blog/2026-03-28-rocky-voice-clone

Local workspace:

```text
../rocky-pi/rocky/
```

Useful pieces from this reference:

- `rocky_say` text transform for Rocky-style grammar.
- Local XTTS voice clone using Rocky reference audio.
- YourTTS/RVC/OpenVoice experiments.
- A persistent XTTS HTTP server to avoid full cold starts.

The key lesson: Rocky style and Rocky audio should be separate layers.

```text
LLM reply -> Rocky text transform -> selected TTS backend
```

### Rocky Gist

Reference:
https://gist.github.com/pedramamini/fa5f6ef99dae79add220188419230642

Vendored in this repo as a submodule:

```text
vendor/rocky-say/rocky_say
```

This gives the project a local, direct source for the Rocky text transform
without depending on the neighboring `rocky-pi` workspace for persona shaping.

### Coyote Interactive

Reference:
https://github.com/gregm123456/coyote_interactive

Useful pieces from this reference:

- Pi-oriented voice assistant shape.
- Push-to-talk / device interaction loop.
- STT, TTS, wake/sleep, logs, and service structure.
- The idea of keeping the physical device loop separate from heavier inference.

The key lesson: the Pi should be a reliable device client first, not the place
where every model has to run.

## Architecture Decision

We chose a Python-only split:

```text
client/
  future Pi loop:
  mic capture, button state, server request, audio playback

server/
  Mac/LAN/hosted-heavy loop:
  STT, LLM, persona transform, TTS, logs, benchmark output
```

For the first scaffold, we implemented typed input before microphone input:

```text
typed prompt -> LLM -> persona transform -> TTS -> WAV -> latency JSONL
```

This let us benchmark the slowest parts before adding STT, microphone handling,
or Pi hardware.

## Implemented Backends

LLM:

- `echo`: no-dependency baseline.
- `ollama`: local Ollama model, currently benchmarked with `llama3.2:1b`.

Persona:

- `none`: no transform.
- `rocky_basic`: tiny built-in fallback.
- `rocky_say`: vendored Rocky gist transform.

TTS:

- `silent`: pipeline test.
- `tone`: transport/playback test, not speech.
- `macos_say`: local macOS speech.
- `rocky_xtts`: direct HTTP call to the warm local Rocky XTTS server.
- `rocky_xtts_cli`: old subprocess compatibility path.
- `rocky_yourtts`: local YourTTS path through `rocky_say`.
- `smallest_ai`: hosted Smallest AI Lightning TTS.

## Iteration 1: Local Rocky Clone

The first cloned-voice path used the existing `rocky_say` script directly.

Initial observation:

- Cold local generation worked, but was slow.
- Warm XTTS through `rocky_say --server start` worked.
- The CLI wrapper still added overhead.

Optimization:

- Read the `rocky_say` source.
- Found that the persistent server exposes a simple local HTTP endpoint.
- Changed `rocky_xtts` to call that HTTP server directly.
- Kept the old CLI path as `rocky_xtts_cli`.

Result:

```text
Tiny Rocky XTTS via old CLI wrapper: ~6.2s TTS
Tiny Rocky XTTS via direct HTTP:     ~4.1s TTS
```

This was a real improvement, but still too slow for natural interaction.

## Iteration 2: Hosted TTS Experiment

We considered hosted providers, especially Bolna and Smallest AI.

Decision:

- Use Smallest AI directly first.
- Defer Bolna because it is more of a full voice-agent orchestration platform.
- Keep our own Python server architecture so providers remain swappable.

Implemented:

- `smallest_ai` TTS backend.
- `rocky-relay-benchmark-tts` command.
- `rocky-relay-smallest-clone` helper.
- `BENCHMARK.md` for latency tracking.

## Benchmark Summary

Latest meaningful benchmark rows:

| Scenario | Backend | Total |
| --- | ---: | ---: |
| TTS-only-ish `hello` | `smallest_ai` | 516ms |
| TTS-only-ish `hello` | `macos_say` | 2746ms |
| TTS-only-ish `hello` | `rocky_xtts` | 4136ms |
| Full Ollama turn | `smallest_ai` | 1206ms |
| Full Ollama turn | `macos_say` | 3536ms |
| Full Ollama turn | `rocky_xtts` | 4889ms |
| Compatibility local clone | `rocky_xtts_cli` | 4721ms |
| Local YourTTS | `rocky_yourtts` | 10184ms |

Interpretation:

- `smallest_ai` is the current fast path.
- `rocky_xtts` is viable as local quality/fun mode, not real-time mode.
- `rocky_yourtts` is too slow in this setup.
- Hosted TTS is already fast enough to justify moving to microphone/STT
  benchmarking.

## Current Direction

Use two voice modes:

```text
fast mode:
  Ollama/STT/persona -> smallest_ai

quality/local Rocky mode:
  Ollama/STT/persona -> rocky_xtts
```

The Pi should remain thin:

```text
Pi:
  button + mic + speaker + HTTP client

Mac/LAN server:
  STT + LLM + persona + TTS backend routing
```

## Next Milestone

Move from typed input to real audio input:

```text
push-to-talk
  -> record short WAV on Mac
  -> send WAV to server
  -> STT
  -> existing LLM/persona/TTS pipeline
  -> play response
```

The next benchmark target should measure:

- Capture duration.
- STT latency.
- LLM latency.
- Persona latency.
- TTS latency.
- Total trigger-to-audio-ready latency.
- Later: trigger-to-first-audible-audio latency.
