# Iteration: STT Benchmarking

Date: 2026-05-03

## Goal

Add speech-to-text to Rocky Relay without disturbing the typed-input benchmark
pipeline.

## Implemented

Added STT backends:

- `smallest_ai`: hosted Smallest AI Pulse STT.
- `whisper_cpp`: local whisper.cpp CLI adapter for later local benchmarking.

`whisper_cpp_no_gpu` defaults to `true`. The first Homebrew `whisper-cli` run
hit a Metal buffer allocation error, and CPU mode is a useful Pi-ish baseline.

Added commands:

- `rocky-relay-turn --audio ...`
- `rocky-relay-benchmark-stt`
- `rocky-relay-make-sample-audio`

The audio turn path is:

```text
audio WAV
  -> STT
  -> LLM
  -> persona transform
  -> TTS
  -> response WAV
  -> JSONL timings
```

## Timing Fields

Audio turns now include:

- `stt_transcription_ms`
- `llm_full_response_ms`
- `persona_transform_ms`
- `tts_generation_ms`
- `total_turn_ms`

## Benchmark Commands

STT-isolated path:

```bash
rocky-relay-benchmark-stt \
  --audio outputs/rocky-direct-test.wav \
  --stt smallest_ai \
  --llm echo \
  --persona none \
  --tts silent
```

Full audio-file path:

```bash
rocky-relay-benchmark-stt \
  --audio outputs/rocky-direct-test.wav \
  --stt smallest_ai \
  --llm ollama \
  --persona rocky_say \
  --tts smallest_ai
```

## Notes

The macOS `say` sample helper can produce empty offline audio in some
non-interactive shells. It now fails loudly if generated audio contains zero
frames. For real benchmarks, use a recorded microphone WAV or a known-good
previous TTS output.

Local `whisper_cpp` was tested with Homebrew `whisper-cli` and
`models/whisper/ggml-base.en.bin`.

Observed on `outputs/rocky-direct-test.wav`:

- Smallest AI STT isolated: about 256-333ms.
- whisper.cpp CPU STT isolated: about 1580ms.
- whisper.cpp CPU + Ollama + silent TTS: about 3190ms total.
- whisper.cpp CPU + Ollama + macOS speech: about 4441ms total.

So far, hosted Smallest STT is much faster, while local whisper.cpp is viable as
an offline fallback.

## References

- Smallest AI Pulse STT quickstart:
  https://docs.smallest.ai/waves/documentation/speech-to-text-pulse/quickstart
