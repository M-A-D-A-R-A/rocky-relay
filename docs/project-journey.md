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

STT:

- `smallest_ai`: hosted Smallest AI Pulse STT for immediate benchmarking.
- `whisper_cpp`: local whisper.cpp CLI adapter for later local benchmarking.

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

Full audio-file pipeline comparison:

| Pipeline | STT | LLM | TTS | Total |
| --- | ---: | ---: | ---: | ---: |
| Smallest STT -> Ollama -> Smallest TTS | 360ms | 624ms | 1001ms | 2044ms |
| whisper.cpp -> Ollama -> macOS TTS | 2521ms | 764ms | 1060ms | 4441ms |
| whisper.cpp -> Ollama -> silent TTS | 2479ms | 563ms | 4ms | 3190ms |
| Smallest STT isolated-ish | 256-333ms | ~0ms | ~5ms | 338ms |
| whisper.cpp STT isolated-ish | 1579ms | ~0ms | ~3ms | 1583ms |

Interpretation:

- `smallest_ai` is the current fast path.
- `rocky_xtts` is viable as local quality/fun mode, not real-time mode.
- `rocky_yourtts` is too slow in this setup.
- `whisper_cpp` works as an offline/local fallback, but CPU mode is much slower
  than hosted Smallest STT on the current short test WAV.
- Hosted TTS is already fast enough to justify moving to microphone/STT
  benchmarking.

## Current Direction

Use two voice modes:

```text
fast mode:
  smallest_ai STT -> Ollama llama3.2:1b -> Rocky text transform -> smallest_ai TTS

quality/local Rocky mode:
  STT -> Ollama llama3.2:1b -> Rocky text transform -> rocky_xtts

offline fallback mode:
  whisper_cpp STT -> Ollama llama3.2:1b -> local or hosted TTS
```

For STT, start with hosted `smallest_ai` so we can benchmark the full user
experience quickly, then compare against local `whisper_cpp` once installed.

After installing Homebrew `whisper-cli` with `ggml-base.en.bin`, local
`whisper_cpp` worked in CPU mode. On the short Rocky test WAV, Smallest STT was
about 256-333ms while whisper.cpp CPU was about 1580ms isolated. In full
audio-file tests, the Smallest STT + Ollama + Smallest TTS path landed around
2.0s total, while whisper.cpp CPU + Ollama + macOS speech landed around 4.4s.

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
audio WAV / push-to-talk
  -> STT backend
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
