import AVFoundation
import Foundation

enum AudioPlayer {
    private static var player: AVAudioPlayer?

    @MainActor
    static func play(data: Data) throws {
        let player = try AVAudioPlayer(data: data)
        player.prepareToPlay()
        player.play()
        self.player = player
    }
}
