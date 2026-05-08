import Foundation

struct RelayClient {
    func health(serverURL: String) async throws -> HealthResponse {
        let url = try endpoint(serverURL: serverURL, path: "/health")
        let (data, response) = try await URLSession.shared.data(from: url)
        try validate(response: response, data: data)
        return try JSONDecoder().decode(HealthResponse.self, from: data)
    }

    func sendAudio(
        audioURL: URL,
        serverURL: String,
        sttBackend: String,
        llmBackend: String,
        ttsBackend: String,
        persona: String,
        conversationID: String?
    ) async throws -> AudioTurnResponse {
        let url = try endpoint(serverURL: serverURL, path: "/audio")
        let audio = try Data(contentsOf: audioURL)
        let requestBody = AudioTurnRequest(
            audioWavBase64: audio.base64EncodedString(),
            sttBackend: sttBackend,
            llmBackend: llmBackend,
            ttsBackend: ttsBackend,
            persona: persona,
            conversationID: conversationID
        )
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(requestBody)

        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response: response, data: data)
        return try JSONDecoder().decode(AudioTurnResponse.self, from: data)
    }

    func sendText(
        text: String,
        serverURL: String,
        llmBackend: String,
        ttsBackend: String,
        persona: String,
        conversationID: String?
    ) async throws -> AudioTurnResponse {
        let url = try endpoint(serverURL: serverURL, path: "/chat")
        let requestBody = TextTurnRequest(
            text: text,
            llmBackend: llmBackend,
            ttsBackend: ttsBackend,
            persona: persona,
            conversationID: conversationID
        )
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(requestBody)

        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response: response, data: data)
        return try JSONDecoder().decode(AudioTurnResponse.self, from: data)
    }

    private func endpoint(serverURL: String, path: String) throws -> URL {
        guard let base = URL(string: serverURL) else {
            throw RelayClientError.invalidServerURL(serverURL)
        }
        return base.appendingPathComponent(path.trimmingCharacters(in: CharacterSet(charactersIn: "/")))
    }

    private func validate(response: URLResponse, data: Data) throws {
        guard let http = response as? HTTPURLResponse else { return }
        guard (200..<300).contains(http.statusCode) else {
            let detail = String(data: data, encoding: .utf8) ?? "unknown error"
            throw RelayClientError.http(status: http.statusCode, detail: detail)
        }
    }
}

struct HealthResponse: Decodable {
    let status: String
    let service: String?
}

struct AudioTurnRequest: Encodable {
    let audioWavBase64: String
    let sttBackend: String
    let llmBackend: String
    let ttsBackend: String
    let persona: String
    let conversationID: String?

    enum CodingKeys: String, CodingKey {
        case audioWavBase64 = "audio_wav_base64"
        case sttBackend = "stt_backend"
        case llmBackend = "llm_backend"
        case ttsBackend = "tts_backend"
        case persona
        case conversationID = "conversation_id"
    }
}

struct TextTurnRequest: Encodable {
    let text: String
    let llmBackend: String
    let ttsBackend: String
    let persona: String
    let conversationID: String?

    enum CodingKeys: String, CodingKey {
        case text
        case llmBackend = "llm_backend"
        case ttsBackend = "tts_backend"
        case persona
        case conversationID = "conversation_id"
    }
}

struct AudioTurnResponse: Decodable {
    let inputText: String
    let spokenText: String
    let audioWavBase64: String?
    let llmMetadata: RelayMetadata?

    var audioData: Data? {
        guard let audioWavBase64 else { return nil }
        return Data(base64Encoded: audioWavBase64)
    }

    enum CodingKeys: String, CodingKey {
        case inputText = "input_text"
        case spokenText = "spoken_text"
        case audioWavBase64 = "audio_wav_base64"
        case llmMetadata = "llm_metadata"
    }
}

struct RelayMetadata: Decodable {
    let suggestions: [RelaySuggestion]?
}

struct RelaySuggestion: Decodable, Identifiable, Equatable {
    let number: Int
    let title: String
    let subtitle: String?
    let price: String?
    let available: Bool?

    var id: Int { number }

    var displaySubtitle: String {
        subtitle?.isEmpty == false ? subtitle! : (available == false ? "Unavailable" : "")
    }
}

enum RelayClientError: LocalizedError {
    case invalidServerURL(String)
    case http(status: Int, detail: String)

    var errorDescription: String? {
        switch self {
        case .invalidServerURL(let url):
            return "Invalid server URL: \(url)"
        case .http(let status, let detail):
            return "Relay server HTTP \(status): \(detail)"
        }
    }
}
