# Iteration: Mac Push-To-Talk

Date: 2026-05-03

## Goal

Move from Enter-to-talk to a Mac-specific global hold-to-talk client while
preserving the server/client split needed for the future Raspberry Pi client.

## Implementation

Added server-first audio turn support:

```text
Mac client captures WAV
  -> POST /audio
  -> server runs STT -> LLM -> persona -> TTS
  -> client receives response WAV
  -> client plays response locally
```

Added commands:

```bash
rocky-relay-audio
rocky-relay-mac-ptt
```

`rocky-relay-mac-ptt` defaults to either macOS Option/Alt key as the global
hold-to-talk trigger. It uses optional `pynput`, installed with:

```bash
pip install -e ".[mac]"
```

## Timing

Mac PTT records client-side timing fields into
`logs/conversations/recorded_turns.jsonl`:

- `capture_duration_ms`
- `network_roundtrip_ms`
- `trigger_to_audio_ready_with_capture_ms`
- `playback_startup_ms`
- `trigger_to_first_audible_ms`

## First Real Run

The first successful Mac PTT conversation used:

```text
conversation_id: conv_fd2bffb617e3
path: Option-key Mac client -> POST /audio -> server processing -> afplay
```

Observed turns:

| Prompt | Capture | Server Audio Ready | Network Roundtrip | First Audible |
| --- | ---: | ---: | ---: | ---: |
| `I don't like movies.` | 3046ms | 3448ms | 3462ms | 6523ms |
| `I am reading Project Helmery currently.` | 4030ms | 1723ms | 1737ms | 5791ms |

Interpretation:

- The architecture worked end-to-end through `/audio`.
- Playback startup was not a bottleneck at roughly 4-8ms.
- The main user-perceived cost was capture duration plus server processing.
- The second turn showed a healthy server-side audio-ready time of about 1.7s.
- The first turn was mostly slowed by Ollama response time at about 2.2s.
- Smallest STT misheard `Project Hail Mary` as `Project Helmery`, but the
  LLM/persona path corrected the reply back to `Project Hail Mary`.

## Notes

macOS may require Accessibility permission for global hotkeys:

```text
System Settings -> Privacy & Security -> Accessibility
```

The Pi client should reuse the same `/audio` endpoint later, swapping the Mac
global hotkey for a physical button press/release loop.
