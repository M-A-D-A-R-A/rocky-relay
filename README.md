# Rocky Relay

Low-latency personal voice assistant experiment inspired by Rocky from
Project Hail Mary.

The goal is to build a small STT -> LLM -> TTS assistant that can eventually
run from a Raspberry Pi 4 device, while using a faster Mac or LAN server for
heavier work when needed.

Phase 1 is Mac-first benchmarking. Before touching the Pi deployment path, this
project should prove the latency, quality, and architecture locally.

## Why This Name

`rocky-relay` captures the intended split:

- Rocky-style voice and phrasing.
- A lightweight device client that relays audio/events.
- A local server that handles expensive speech and language work.

## References

- Rocky voice clone write-up:
  https://pedsidian.pedramamini.com/Claude/Blog/2026-03-28-rocky-voice-clone
- Coyote Interactive:
  https://github.com/gregm123456/coyote_interactive
- Local tested Rocky clone assets:
  `../rocky-pi/rocky/`

## Product Goal

Build a personal low-latency voice assistant with:

- Push-to-talk interaction first.
- Fast speech-to-text.
- Local LLM replies where practical.
- Swappable text-to-speech backends.
- Optional Rocky-style speech transform.
- Optional Rocky cloned voice generation.
- Pi 4 as the eventual physical interface.

The first milestone is not a perfect clone. The first milestone is an honest
latency benchmark and a usable loop.

## Architecture

The project should start with two runnable components, even on the Mac:

```text
client/
  Captures microphone audio.
  Sends audio to the server.
  Plays returned speech.
  Later maps cleanly to the Raspberry Pi 4.

server/
  Receives audio.
  Runs STT.
  Calls the LLM.
  Applies persona / Rocky text shaping.
  Runs TTS.
  Returns WAV/audio to the client.
```

Initial local flow:

```text
push-to-talk
  -> capture microphone audio
  -> send audio to local server
  -> transcribe with STT
  -> generate reply with LLM
  -> optionally transform into Rocky-speak
  -> synthesize speech
  -> return audio
  -> play response
```

## Proposed Stack

Mac benchmark stack:

- STT: `whisper.cpp` or `whisper-stream`
- LLM: Ollama-served local model
- Low-latency TTS baseline: Piper
- Rocky cloned TTS: local `rocky_say` integration
- Interaction mode: push-to-talk
- Transport: local HTTP/WebSocket between client and server

Future Pi stack:

- Pi 4: microphone, button, speaker, LEDs, simple client loop
- LAN server: STT, LLM, cloned TTS, benchmarking logs
- Optional Pi-local TTS only if latency and quality are acceptable

## TTS Backends

TTS should be swappable from day one:

```text
piper
  Fast baseline.
  Best for measuring what "good latency" feels like.

rocky_xtts
  Uses the local Rocky voice reference through XTTS.
  Better character identity, slower generation.

rocky_yourtts
  Uses the Rocky reference through YourTTS.
  Worth benchmarking because the Rocky script describes it as fast and high quality.
```

The persona layer should stay separate from the voice engine:

```text
LLM reply
  -> optional Rocky text transform
  -> selected TTS backend
```

This lets us compare:

- Plain assistant text with Piper.
- Rocky-styled text with Piper.
- Plain assistant text with Rocky cloned TTS.
- Rocky-styled text with Rocky cloned TTS.

## Latency Metrics

Every turn should log:

- Capture duration.
- Upload / request overhead.
- STT latency.
- LLM first-token latency.
- LLM full-response latency.
- Persona transform latency.
- TTS generation latency.
- Playback start latency.
- Total trigger-to-first-audio latency.
- Total trigger-to-finished-playback latency.

The key user-experience number is:

```text
button press -> first audible response
```

## Benchmark Scenarios

Run each scenario cold and warm:

- Typed text -> LLM -> TTS.
- 1-second spoken prompt -> STT -> LLM -> TTS.
- 3-second spoken prompt -> STT -> LLM -> TTS.
- 6-second spoken prompt -> STT -> LLM -> TTS.
- Piper backend.
- Rocky XTTS backend.
- Rocky YourTTS backend.
- With and without Rocky text transform.

## Phases

### Phase 0: Project Skeleton

- Create `client` and `server` directories.
- Add shared latency logging.
- Add typed-input smoke test.
- Add backend configuration.

### Phase 1: Mac Benchmark

- Implement push-to-talk client on Mac.
- Implement local server.
- Integrate STT.
- Integrate Ollama.
- Integrate Piper.
- Integrate local Rocky TTS script.
- Produce benchmark logs.

### Phase 2: Pi Client Prototype

- Move only the client loop to Raspberry Pi 4.
- Keep server on Mac/LAN machine.
- Test USB mic, physical button, and speaker.
- Add LEDs or simple hardware state indicators.

### Phase 3: Latency Decisions

Use measured data to decide:

- What can run safely on the Pi.
- What must stay on the LAN server.
- Whether Piper is enough for fast mode.
- Whether Rocky cloned TTS is acceptable for normal use.
- Whether true voice-clone R&D is worth deeper investment.

## Non-Goals For V1

- No wake word in the first pass.
- No always-listening mode in the first pass.
- No Pi deployment before Mac latency is measured.
- No commercial use.
- No claim of official Project Hail Mary affiliation.

## Local Rocky Assets

The existing tested Rocky clone lives beside this project:

```text
../rocky-pi/rocky/rocky_say
../rocky-pi/rocky/rocky_training_audio_scrubbed.wav
../rocky-pi/rocky/rocky_voice.pth
```

Useful local checks:

```bash
python3 ../rocky-pi/rocky/rocky_say --transform-only "Hello, how are you doing today?"
python3 ../rocky-pi/rocky/rocky_say --server status
python3 ../rocky-pi/rocky/rocky_say --server start --agree-cpml
```

## Git Initialization

From this folder:

```bash
git init
git add README.md
git commit -m "Initial Rocky Relay project brief"
```

## First Build Target

The first real implementation target should be:

```text
typed prompt
  -> server
  -> Ollama reply
  -> selected TTS backend
  -> WAV file
  -> latency JSON log
```

After that works, add microphone capture and push-to-talk.
