# Rocky Companion

Mac-only Swift companion app for Rocky Relay.

This is intentionally separate from the Python backend:

```text
Rocky Relay Python server
  STT -> LLM -> persona -> TTS
  exposes /health and /audio

Rocky Companion Swift app
  Dock-line Rocky companion
  microphone capture
  sends WAV to /audio
  plays response WAV
```

The structure is inspired by `agentrocky`:
https://github.com/itmesneha/agentrocky

It borrows the idea of a floating always-on-top Rocky presence, speech/status
bubbles, and Dock-line walking. Unlike `agentrocky`, this app does not run
Claude Code. It talks to the existing Rocky Relay HTTP API.

The pixel Rocky sprites are adapted from the `agentrocky` reference:

```text
RockyCompanion/Resources/Sprites/
  stand.png
  walkleft1.png
  walkleft2.png
  jazz1.png
  jazz2.png
  jazz3.png
```

## Layout

```text
RockyCompanion/
  *.swift                  App source.
  Resources/Sprites/       Pixel Rocky animation frames.
  Resources/Assets.xcassets
  Support/                 Xcode-only support files.
RockyCompanion.xcodeproj/  Optional full-Xcode project.
Package.swift              SwiftPM fallback for Command Line Tools.
```

## Run

Start the Python server first:

```bash
rocky-relay-server
```

If you have full Xcode installed, open the companion project:

```bash
open mac-companion/RockyCompanion.xcodeproj
```

Press `Cmd+R` in Xcode.

If the project opens in Finder, Xcode is not installed or not associated with
`.xcodeproj` files. You can still build/run the MVP with Swift Package Manager:

```bash
cd mac-companion
swift run RockyCompanion
```

## Current MVP

- Transparent always-on-top Rocky overlay with no panel chrome.
- Animated pixel Rocky using stand, walk, and jazz frames.
- Rocky walks horizontally along the Dock line while idle.
- Click Rocky, press `Tab`, press `Enter`, or press `Space` to toggle recording.
- Sends WAV to `POST /audio`.
- Shows the transcript and Rocky response as speech bubbles hovering over Rocky.
- Clears the bubbles after a few seconds while keeping only the last conversation.
- Plays returned WAV audio.

## Notes

- macOS will ask for microphone permission.
- Global Tab/Enter/Space only work when macOS allows keyboard event monitoring.
  Click Rocky once to focus the companion if the first key press does not toggle.
- The Swift companion is Mac-only demo/UI surface.
- The Pi client should still use the same `/audio` API later.
