import AppKit
import SwiftUI

struct CompanionView: View {
    @ObservedObject var state: CompanionState
    @StateObject private var recorder = AudioRecorder()
    @State private var walkFrame = 0
    @State private var jazzFrame = 0
    private let animationTimer = Timer.publish(every: 0.16, on: .main, in: .common).autoconnect()

    var body: some View {
        ZStack {
            Color.clear

            VStack(spacing: 8) {
                bubbleStack
                suggestionList
                Button {
                    toggleRecording()
                } label: {
                    RockySprite(
                        status: state.status,
                        isJazzing: state.isJazzing,
                        walkFrame: walkFrame,
                        jazzFrame: jazzFrame,
                        direction: state.direction
                    )
                }
                .buttonStyle(.plain)

                Text("tab / enter / space")
                    .font(.system(size: 10, weight: .semibold, design: .monospaced))
                    .foregroundColor(.white.opacity(0.55))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(Capsule().fill(Color.black.opacity(0.45)))
            }

            keyboardShortcuts
        }
        .frame(width: 380, height: 420)
        .onReceive(animationTimer) { _ in
            tickSprite()
        }
        .onReceive(NotificationCenter.default.publisher(for: .rockyToggleRecording)) { _ in
            toggleRecording()
        }
    }

    private var keyboardShortcuts: some View {
        Group {
            Button("") { toggleRecording() }
                .keyboardShortcut(.return, modifiers: [])
            Button("") { toggleRecording() }
                .keyboardShortcut(.tab, modifiers: [])
            Button("") { toggleRecording() }
                .keyboardShortcut(.space, modifiers: [])
        }
        .frame(width: 0, height: 0)
        .opacity(0)
        .accessibilityHidden(true)
    }

    private var bubbleStack: some View {
        VStack(spacing: 5) {
            SpeechBubble(text: state.bubble, color: .green)

            if let userBubble = state.userBubble {
                SpeechBubble(text: userBubble, color: .cyan)
            }

            if let rockyBubble = state.rockyBubble {
                SpeechBubble(text: rockyBubble, color: .white)
            }

            if let error = state.errorMessage {
                SpeechBubble(text: error, color: .red)
            }
        }
        .frame(maxWidth: 330)
        .animation(.spring(response: 0.25, dampingFraction: 0.75), value: state.bubble)
        .animation(.spring(response: 0.25, dampingFraction: 0.75), value: state.userBubble)
        .animation(.spring(response: 0.25, dampingFraction: 0.75), value: state.rockyBubble)
    }

    @ViewBuilder
    private var suggestionList: some View {
        if !state.suggestions.isEmpty {
            SuggestionList(
                suggestions: state.suggestions,
                isEnabled: state.status == .idle
            ) { suggestion in
                Task { await state.selectSuggestion(suggestion) }
            }
            .transition(.move(edge: .top).combined(with: .opacity))
        }
    }
}

struct SuggestionList: View {
    let suggestions: [RelaySuggestion]
    let isEnabled: Bool
    let onSelect: (RelaySuggestion) -> Void

    var body: some View {
        ScrollView {
            VStack(spacing: 6) {
                ForEach(suggestions) { suggestion in
                    Button {
                        onSelect(suggestion)
                    } label: {
                        SuggestionRow(suggestion: suggestion)
                    }
                    .buttonStyle(.plain)
                    .disabled(suggestion.available == false || !isEnabled)
                    .opacity(suggestion.available == false ? 0.48 : 1)
                }
            }
            .padding(6)
        }
        .frame(width: 342)
        .frame(maxHeight: 138)
        .background(suggestionBackground)
        .animation(.spring(response: 0.25, dampingFraction: 0.8), value: suggestions)
    }

    private var suggestionBackground: some View {
        RoundedRectangle(cornerRadius: 8)
            .fill(Color.black.opacity(0.7))
            .overlay(
                RoundedRectangle(cornerRadius: 8)
                    .stroke(Color.green.opacity(0.35), lineWidth: 1)
            )
            .shadow(color: .black.opacity(0.22), radius: 5, x: 0, y: 2)
    }
}

private extension CompanionView {
    func toggleRecording() {
        if recorder.isRecording {
            guard let url = recorder.stop() else { return }
            state.status = .thinking
            state.bubble = "rocky thinking"
            Task { await state.send(audioURL: url) }
        } else {
            do {
                try recorder.start()
                state.status = .listening
                state.bubble = "rocky listening"
                state.userBubble = nil
                state.rockyBubble = nil
                state.errorMessage = nil
            } catch {
                state.status = .error
                state.bubble = "mic bad"
                state.errorMessage = error.localizedDescription
            }
        }
    }

    func tickSprite() {
        if state.isJazzing {
            jazzFrame = (jazzFrame + 1) % 3
            return
        }
        walkFrame = (walkFrame + 1) % 2
    }
}

struct SuggestionRow: View {
    let suggestion: RelaySuggestion

    var body: some View {
        HStack(spacing: 8) {
            Text("\(suggestion.number)")
                .font(.system(size: 12, weight: .bold, design: .monospaced))
                .foregroundColor(.black)
                .frame(width: 22, height: 22)
                .background(Circle().fill(Color.green.opacity(0.95)))

            VStack(alignment: .leading, spacing: 2) {
                Text(suggestion.title)
                    .font(.system(size: 12, weight: .bold, design: .monospaced))
                    .foregroundColor(.white)
                    .lineLimit(1)

                if !suggestion.displaySubtitle.isEmpty {
                    Text(suggestion.displaySubtitle)
                        .font(.system(size: 10, weight: .semibold, design: .monospaced))
                        .foregroundColor(.white.opacity(0.68))
                        .lineLimit(1)
                }
            }

            Spacer(minLength: 4)
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 7)
        .background(
            RoundedRectangle(cornerRadius: 8)
                .fill(Color.white.opacity(0.08))
        )
        .contentShape(RoundedRectangle(cornerRadius: 8))
    }
}

struct SpeechBubble: View {
    let text: String
    let color: Color

    var body: some View {
        Text(text)
            .font(.system(size: 12, weight: .bold, design: .monospaced))
            .foregroundColor(color == .white ? .black : color)
            .lineLimit(3)
            .multilineTextAlignment(.center)
            .padding(.horizontal, 11)
            .padding(.vertical, 7)
            .background(
                RoundedRectangle(cornerRadius: 12)
                    .fill(color == .white ? Color.white.opacity(0.94) : Color.black.opacity(0.78))
                    .overlay(
                        RoundedRectangle(cornerRadius: 12)
                            .stroke(color.opacity(0.45), lineWidth: 1)
                    )
                    .shadow(color: .black.opacity(0.22), radius: 5, x: 0, y: 2)
            )
    }
}

struct RockySprite: View {
    let status: CompanionStatus
    let isJazzing: Bool
    let walkFrame: Int
    let jazzFrame: Int
    let direction: CGFloat

    private var spriteName: String {
        if isJazzing {
            return "jazz\(jazzFrame + 1)"
        }
        if status == .listening || status == .thinking || status == .speaking {
            return "stand"
        }
        return walkFrame == 0 ? "walkleft1" : "walkleft2"
    }

    var body: some View {
        ZStack {
            if let image = loadImage(named: spriteName) {
                Image(nsImage: image)
                    .resizable()
                    .interpolation(.none)
                    .scaledToFit()
                    .scaleEffect(x: direction > 0 ? -1 : 1, y: 1)
            } else {
                RoundedRectangle(cornerRadius: 14)
                    .fill(Color.green)
                    .overlay(Text("R").font(.largeTitle.bold()))
            }
        }
        .frame(width: 96, height: 96)
        .contentShape(Rectangle())
    }

    private func loadImage(named name: String) -> NSImage? {
        if let image = NSImage(named: name) {
            return image
        }
        let candidateURLs = [
            Bundle.module.url(forResource: name, withExtension: "png"),
            Bundle.module.url(forResource: name, withExtension: "png", subdirectory: "Sprites"),
            Bundle.module.url(forResource: name, withExtension: "png", subdirectory: "Resources/Sprites"),
        ].compactMap { $0 }

        for url in candidateURLs {
            if let image = NSImage(contentsOf: url) {
                return image
            }
        }
        return nil
    }
}
