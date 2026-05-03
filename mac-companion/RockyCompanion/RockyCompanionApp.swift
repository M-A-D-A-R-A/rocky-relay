import AppKit
import SwiftUI

@main
struct RockyCompanionApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate

    var body: some Scene {
        Settings {
            EmptyView()
        }
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var panel: NSPanel?
    private let state = CompanionState()
    private var moveTimer: Timer?
    private var localKeyMonitor: Any?
    private var globalKeyMonitor: Any?
    private var lastTick = Date()
    private var horizontalSpeed: CGFloat = 120

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        setupPanel()
        startDockWalk()
        startKeyMonitoring()
        Task { await state.checkHealth() }
    }

    private func setupPanel() {
        let width: CGFloat = 360
        let height: CGFloat = 230
        let panel = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: width, height: height),
            styleMask: [.borderless],
            backing: .buffered,
            defer: false
        )
        panel.isFloatingPanel = true
        panel.level = .floating
        panel.backgroundColor = .clear
        panel.isOpaque = false
        panel.hasShadow = false
        panel.hidesOnDeactivate = false
        panel.collectionBehavior = [.canJoinAllSpaces, .stationary]

        if let screen = NSScreen.main {
            let visible = screen.visibleFrame
            let startX = min(max(visible.maxX - width - 24, visible.minX), visible.maxX - width)
            panel.setFrameOrigin(NSPoint(x: startX, y: dockLineY(for: screen)))
        }

        panel.contentView = NSHostingView(rootView: CompanionView(state: state))
        panel.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        self.panel = panel
    }

    private func startDockWalk() {
        lastTick = Date()
        moveTimer = Timer.scheduledTimer(withTimeInterval: 1.0 / 60.0, repeats: true) { [weak self] _ in
            Task { @MainActor in
                self?.walkDockLine()
            }
        }
    }

    private func walkDockLine() {
        guard let panel, let screen = NSScreen.main else {
            return
        }

        let now = Date()
        let dt = now.timeIntervalSince(lastTick)
        lastTick = now

        let visible = screen.visibleFrame
        let minX = visible.minX
        let maxX = max(visible.minX, visible.maxX - panel.frame.width)
        var origin = panel.frame.origin
        origin.y = dockLineY(for: screen)

        if state.status == .idle && !state.isJazzing {
            origin.x += horizontalSpeed * dt

            if origin.x <= minX {
                origin.x = minX
                horizontalSpeed = abs(horizontalSpeed)
            } else if origin.x >= maxX {
                origin.x = maxX
                horizontalSpeed = -abs(horizontalSpeed)
            }

            state.direction = horizontalSpeed >= 0 ? 1 : -1
        } else {
            origin.x = min(max(origin.x, minX), maxX)
        }

        panel.setFrameOrigin(origin)
    }

    private func dockLineY(for screen: NSScreen) -> CGFloat {
        screen.visibleFrame.minY
    }

    private func startKeyMonitoring() {
        localKeyMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
            if Self.shouldToggle(for: event) {
                NotificationCenter.default.post(name: .rockyToggleRecording, object: nil)
                return nil
            }
            return event
        }
        globalKeyMonitor = NSEvent.addGlobalMonitorForEvents(matching: .keyDown) { event in
            if Self.shouldToggle(for: event) {
                NotificationCenter.default.post(name: .rockyToggleRecording, object: nil)
            }
        }
    }

    private static func shouldToggle(for event: NSEvent) -> Bool {
        guard !event.isARepeat else { return false }
        return event.keyCode == 36 || event.keyCode == 48 || event.keyCode == 49
    }
}
