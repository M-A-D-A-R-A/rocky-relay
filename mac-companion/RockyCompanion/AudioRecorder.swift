import AVFoundation
import Foundation

@MainActor
final class AudioRecorder: NSObject, ObservableObject, AVAudioRecorderDelegate {
    @Published private(set) var isRecording = false
    private var recorder: AVAudioRecorder?
    private(set) var currentURL: URL?

    func start() throws {
        let directory = FileManager.default.temporaryDirectory
        let url = directory.appendingPathComponent("rocky-companion-\(UUID().uuidString).wav")
        let settings: [String: Any] = [
            AVFormatIDKey: kAudioFormatLinearPCM,
            AVSampleRateKey: 16_000,
            AVNumberOfChannelsKey: 1,
            AVLinearPCMBitDepthKey: 16,
            AVLinearPCMIsFloatKey: false,
            AVLinearPCMIsBigEndianKey: false
        ]
        let recorder = try AVAudioRecorder(url: url, settings: settings)
        recorder.delegate = self
        recorder.prepareToRecord()
        recorder.record()
        self.recorder = recorder
        self.currentURL = url
        self.isRecording = true
    }

    func stop() -> URL? {
        recorder?.stop()
        recorder = nil
        isRecording = false
        return currentURL
    }
}
