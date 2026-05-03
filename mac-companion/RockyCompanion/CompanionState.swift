import Foundation
import CoreGraphics

@MainActor
final class CompanionState: ObservableObject {
    @Published var serverURL: String = "http://127.0.0.1:8765"
    @Published var status: CompanionStatus = .idle
    @Published var bubble: String = "rocky ready?"
    @Published var userBubble: String?
    @Published var rockyBubble: String?
    @Published var lastUserText: String?
    @Published var lastRockyText: String?
    @Published var lines: [ConversationLine] = []
    @Published var errorMessage: String?
    @Published var isJazzing: Bool = false
    @Published var direction: CGFloat = 1

    let relay = RelayClient()

    func checkHealth() async {
        status = .thinking
        bubble = "checking server"
        do {
            let health = try await relay.health(serverURL: serverURL)
            bubble = "server \(health.status)"
            status = .idle
            errorMessage = nil
        } catch {
            bubble = "server missing"
            status = .error
            errorMessage = error.localizedDescription
        }
    }

    func send(audioURL: URL) async {
        status = .thinking
        bubble = "rocky thinking"
        userBubble = nil
        rockyBubble = nil
        do {
            let result = try await relay.sendAudio(
                audioURL: audioURL,
                serverURL: serverURL,
                sttBackend: "smallest_ai",
                llmBackend: "ollama",
                ttsBackend: "smallest_ai",
                persona: "rocky_say_llm"
            )
            lastUserText = result.inputText
            lastRockyText = result.spokenText
            lines = [
                .init(speaker: "You", text: result.inputText),
                .init(speaker: "Rocky", text: result.spokenText)
            ]
            userBubble = "You: \(result.inputText)"
            rockyBubble = "Rocky: \(result.spokenText)"
            if let audio = result.audioData {
                status = .speaking
                bubble = "rocky speaking"
                try AudioPlayer.play(data: audio)
            }
            bubble = "rocky done!"
            status = .idle
            triggerJazz()
            clearBubblesLater()
            errorMessage = nil
        } catch {
            bubble = "bad bad bad"
            status = .error
            errorMessage = error.localizedDescription
        }
    }

    func triggerJazz() {
        isJazzing = true
        Task {
            try? await Task.sleep(nanoseconds: 2_400_000_000)
            await MainActor.run {
                self.isJazzing = false
            }
        }
    }

    func clearBubblesLater() {
        Task {
            try? await Task.sleep(nanoseconds: 6_000_000_000)
            await MainActor.run {
                guard self.status == .idle else { return }
                self.bubble = "rocky ready?"
                self.userBubble = nil
                self.rockyBubble = nil
                self.errorMessage = nil
            }
        }
    }
}

enum CompanionStatus {
    case idle
    case listening
    case thinking
    case speaking
    case error

    var label: String {
        switch self {
        case .idle: return "idle"
        case .listening: return "listening"
        case .thinking: return "thinking"
        case .speaking: return "speaking"
        case .error: return "error"
        }
    }
}

struct ConversationLine: Identifiable {
    let id = UUID()
    let speaker: String
    let text: String
}
