import AppKit
import AVFoundation

final class AppDelegate: NSObject, NSApplicationDelegate {
    private enum Mode {
        case idle
        case holdRecording    // Right ⌥ held
        case lockedRecording  // double-tapped Right ⌥: hands-free
        case commandRecording // Right ⌘ held: spoken edit of the selection
    }

    private var statusItem: NSStatusItem!
    private var lastRecordingItem: NSMenuItem!
    private let hotkey = HotkeyListener()
    private let recorder = AudioRecorder()
    private let injector = TextInjector()
    private let hud = HUD()
    private var outboxTimer: Timer?
    private var silenceTimer: Timer?

    private var mode: Mode = .idle
    private var lastShortRelease: Date?      // double-tap detection
    private let doubleTapWindow: TimeInterval = 0.4
    private let minHoldDuration: TimeInterval = 0.35
    private let silenceStop: TimeInterval = 2.5
    private let handsFreeCap: TimeInterval = 120

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

        hotkey.onPress = { [weak self] kind in self?.keyPressed(kind) }
        hotkey.onRelease = { [weak self] kind in self?.keyReleased(kind) }
        if !hotkey.start() {
            alert("Flow needs Input Monitoring access to see the hotkeys.",
                  "Enable Flow in System Settings → Privacy & Security → Input Monitoring, then relaunch.")
            NSWorkspace.shared.open(URL(string:
                "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent")!)
        }
    }

    // MARK: - Hotkey state machine

    private func keyPressed(_ kind: HotkeyKind) {
        switch (kind, mode) {
        case (.dictate, .idle):
            if let t = lastShortRelease, Date().timeIntervalSince(t) < doubleTapWindow {
                lastShortRelease = nil
                beginRecording(mode: .lockedRecording)
            } else {
                beginRecording(mode: .holdRecording)
            }
        case (.dictate, .lockedRecording):
            endRecording() // tap again to stop hands-free
        case (.command, .idle):
            guard injector.trusted else {
                hud.show("Command mode needs Accessibility permission", autoHide: 3)
                return
            }
            beginRecording(mode: .commandRecording)
        default:
            break
        }
    }

    private func keyReleased(_ kind: HotkeyKind) {
        switch (kind, mode) {
        case (.dictate, .holdRecording):
            let held = Date().timeIntervalSince(recorder.startedAt ?? Date())
            if held < minHoldDuration {
                cancelRecording()
                lastShortRelease = Date() // may be the first tap of a double-tap
            } else {
                endRecording()
            }
        case (.command, .commandRecording):
            endRecording()
        default:
            break
        }
    }

    // MARK: - Recording

    private func beginRecording(mode newMode: Mode) {
        guard !recorder.isRecording else { return }

        // capture context BEFORE anything else: frontmost app + selection
        let front = NSWorkspace.shared.frontmostApplication
        var meta: [String: Any] = [
            "app_name": front?.localizedName ?? "",
            "bundle_id": front?.bundleIdentifier ?? "",
            "mode": newMode == .commandRecording ? "command" : "dictate",
        ]
        if newMode == .commandRecording {
            let selection = injector.captureSelection()
            guard !selection.isEmpty else {
                hud.show("Select some text first, then hold Right ⌘", autoHide: 3)
                return
            }
            meta["selection"] = selection
        }

        let stem = "rec-\(stampFormatter.string(from: Date()))"
        let url = recordingsDir.appendingPathComponent("\(stem).wav")
        do {
            try recorder.start(writingTo: url)
        } catch {
            alert("Could not start recording", error.localizedDescription)
            return
        }
        if let data = try? JSONSerialization.data(withJSONObject: meta) {
            try? data.write(to: recordingsDir.appendingPathComponent("\(stem).meta.json"))
        }

        lastRecordingURL = url
        mode = newMode
        statusItem.button?.title = "🔴"
        switch newMode {
        case .holdRecording: hud.show("🔴  Listening…")
        case .lockedRecording:
            hud.show("🔴  Listening — tap Right ⌥ or pause to finish")
            startSilenceWatch()
        case .commandRecording: hud.show("🟣  Command — say what to do with the selection")
        case .idle: break
        }
    }

    private func endRecording() {
        guard recorder.isRecording else { return }
        stopSilenceWatch()
        recorder.stop()
        mode = .idle
        statusItem.button?.title = "⏳"
        hud.show("⏳  Transcribing…")
        lastRecordingItem.title = "Reveal last recording (\(lastRecordingURL?.lastPathComponent ?? ""))"
        NSSound(named: "Pop")?.play()
        // if no transcript arrives (watcher not running), don't hang on ⏳
        DispatchQueue.main.asyncAfter(deadline: .now() + 30) {
            if self.statusItem.button?.title == "⏳" {
                self.statusItem.button?.title = "🎤"
                self.hud.hide()
            }
        }
    }

    private func cancelRecording() {
        stopSilenceWatch()
        recorder.stop()
        mode = .idle
        statusItem.button?.title = "🎤"
        hud.hide()
        if let url = lastRecordingURL {
            try? FileManager.default.removeItem(at: url)
            let meta = url.deletingPathExtension().appendingPathExtension("meta.json")
            try? FileManager.default.removeItem(at: meta)
        }
    }

    // MARK: - Hands-free silence auto-stop

    private func startSilenceWatch() {
        silenceTimer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in
            guard let self, self.mode == .lockedRecording else { return }
            let elapsed = Date().timeIntervalSince(self.recorder.startedAt ?? Date())
            if elapsed > self.handsFreeCap { self.endRecording(); return }
            if self.recorder.voiceDetected,
               let last = self.recorder.lastVoiceAt,
               Date().timeIntervalSince(last) > self.silenceStop {
                self.endRecording()
            }
        }
    }

    private func stopSilenceWatch() {
        silenceTimer?.invalidate()
        silenceTimer = nil
    }

    // MARK: - Outbox (transcripts back from the Python watcher)

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
            guard !trimmed.isEmpty else {
                statusItem.button?.title = "🎤"
                continue
            }
            let typed = injector.inject(trimmed)
            statusItem.button?.title = typed ? "🎤" : "📋"
            hud.show((typed ? "⌨️  " : "📋  ") + trimmed, autoHide: 2.5)
            if !typed {
                DispatchQueue.main.asyncAfter(deadline: .now() + 3) {
                    self.statusItem.button?.title = "🎤"
                }
            }
        }
    }

    // MARK: - Menu / chrome

    private func setUpMenu() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.title = "🎤"

        let menu = NSMenu()
        menu.addItem(withTitle: "Hold Right ⌥ to dictate (double-tap: hands-free)", action: nil, keyEquivalent: "")
        menu.addItem(withTitle: "Select text + hold Right ⌘ to voice-edit", action: nil, keyEquivalent: "")
        lastRecordingItem = menu.addItem(withTitle: "No recording yet",
                                         action: #selector(revealLastRecording), keyEquivalent: "")
        lastRecordingItem.target = self
        menu.addItem(.separator())
        menu.addItem(withTitle: "Quit Flow", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        statusItem.menu = menu
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
