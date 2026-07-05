import AppKit
import AVFoundation

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem!
    private var lastRecordingItem: NSMenuItem!
    private let hotkey = HotkeyListener()
    private let recorder = AudioRecorder()
    private let injector = TextInjector()
    private var outboxTimer: Timer?

    private let recordingsDir = FileManager.default
        .homeDirectoryForCurrentUser
        .appendingPathComponent("Flow/recordings", isDirectory: true)
    private let outboxDir = FileManager.default
        .homeDirectoryForCurrentUser
        .appendingPathComponent("Flow/outbox", isDirectory: true)
    private var lastRecordingURL: URL?

    private let stampFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyyMMdd-HHmmss"
        return f
    }()

    func applicationDidFinishLaunching(_ notification: Notification) {
        try? FileManager.default.createDirectory(at: recordingsDir, withIntermediateDirectories: true)
        try? FileManager.default.createDirectory(at: outboxDir, withIntermediateDirectories: true)
        setUpMenu()

        // Prompt for Accessibility (needed to type text into other apps).
        let promptKey = kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String
        AXIsProcessTrustedWithOptions([promptKey: true] as CFDictionary)
        startOutboxWatcher()

        AudioRecorder.requestMicAccess { granted in
            if !granted { self.alert("Flow needs microphone access.",
                                     "Grant it in System Settings → Privacy & Security → Microphone, then relaunch.") }
        }

        hotkey.onPress = { [weak self] in self?.beginRecording() }
        hotkey.onRelease = { [weak self] in self?.endRecording() }
        if !hotkey.start() {
            alert("Flow needs Input Monitoring access to see the hotkey.",
                  "Enable Flow in System Settings → Privacy & Security → Input Monitoring, then relaunch.")
            NSWorkspace.shared.open(URL(string:
                "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent")!)
        }
    }

    private func setUpMenu() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.title = "🎤"

        let menu = NSMenu()
        menu.addItem(withTitle: "Hold Right ⌥ to dictate", action: nil, keyEquivalent: "")
        lastRecordingItem = menu.addItem(withTitle: "No recording yet",
                                         action: #selector(revealLastRecording), keyEquivalent: "")
        lastRecordingItem.target = self
        menu.addItem(.separator())
        menu.addItem(withTitle: "Quit Flow", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        statusItem.menu = menu
    }

    private func beginRecording() {
        guard !recorder.isRecording else { return }
        // Timestamped so every dictation is kept — the watcher logs each one.
        let name = "rec-\(stampFormatter.string(from: Date())).wav"
        let url = recordingsDir.appendingPathComponent(name)
        do {
            try recorder.start(writingTo: url)
            lastRecordingURL = url
            statusItem.button?.title = "🔴"
        } catch {
            alert("Could not start recording", error.localizedDescription)
        }
    }

    private func endRecording() {
        guard recorder.isRecording else { return }
        recorder.stop()
        statusItem.button?.title = "⏳" // transcribing; outbox watcher resets it
        lastRecordingItem.title = "Reveal last recording (\(lastRecordingURL?.lastPathComponent ?? ""))"
        NSSound(named: "Pop")?.play()
        // if no transcript arrives (watcher not running), don't hang on ⏳
        DispatchQueue.main.asyncAfter(deadline: .now() + 30) {
            if self.statusItem.button?.title == "⏳" { self.statusItem.button?.title = "🎤" }
        }
    }

    /// The Python watcher drops each cleaned transcript into ~/Flow/outbox;
    /// we consume it and type it into the frontmost app.
    private func startOutboxWatcher() {
        outboxTimer = Timer.scheduledTimer(withTimeInterval: 0.25, repeats: true) { [weak self] _ in
            self?.drainOutbox()
        }
    }

    private func drainOutbox() {
        guard let files = try? FileManager.default.contentsOfDirectory(
            at: outboxDir, includingPropertiesForKeys: nil) else { return }
        for file in files where file.pathExtension == "txt" {
            guard let text = try? String(contentsOf: file, encoding: .utf8) else { continue }
            try? FileManager.default.removeItem(at: file)
            let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
            if !trimmed.isEmpty {
                let typed = injector.inject(trimmed)
                statusItem.button?.title = typed ? "🎤" : "📋"
                if !typed {
                    // no Accessibility yet: text stays on the clipboard
                    DispatchQueue.main.asyncAfter(deadline: .now() + 3) {
                        self.statusItem.button?.title = "🎤"
                    }
                }
            } else {
                statusItem.button?.title = "🎤"
            }
        }
    }

    @objc private func revealLastRecording() {
        guard let url = lastRecordingURL else { return }
        NSWorkspace.shared.activateFileViewerSelecting([url])
    }

    private func alert(_ title: String, _ text: String) {
        let a = NSAlert()
        a.messageText = title
        a.informativeText = text
        a.runModal()
    }
}
