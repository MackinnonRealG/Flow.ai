import AppKit

/// A small floating pill near the bottom of the screen showing what Flow is
/// doing: listening, transcribing, or the text it just typed.
final class HUD {
    private let panel: NSPanel
    private let label: NSTextField
    private var hideTask: DispatchWorkItem?

    init() {
        let size = NSSize(width: 340, height: 40)
        panel = NSPanel(
            contentRect: NSRect(origin: .zero, size: size),
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered, defer: true
        )
        panel.level = .statusBar
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.ignoresMouseEvents = true
        panel.hidesOnDeactivate = false
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]

        let background = NSView(frame: NSRect(origin: .zero, size: size))
        background.wantsLayer = true
        background.layer?.backgroundColor = NSColor.black.withAlphaComponent(0.82).cgColor
        background.layer?.cornerRadius = 20

        label = NSTextField(labelWithString: "")
        label.textColor = .white
        label.font = .systemFont(ofSize: 14, weight: .medium)
        label.alignment = .center
        label.lineBreakMode = .byTruncatingTail
        label.maximumNumberOfLines = 1
        label.frame = NSRect(x: 16, y: 10, width: size.width - 32, height: 20)
        label.autoresizingMask = [.width]

        background.addSubview(label)
        panel.contentView = background
    }

    func show(_ text: String, autoHide seconds: TimeInterval? = nil) {
        hideTask?.cancel()
        label.stringValue = text
        position()
        panel.orderFrontRegardless()
        if let seconds {
            let task = DispatchWorkItem { [weak self] in self?.panel.orderOut(nil) }
            hideTask = task
            DispatchQueue.main.asyncAfter(deadline: .now() + seconds, execute: task)
        }
    }

    func hide() {
        hideTask?.cancel()
        panel.orderOut(nil)
    }

    private func position() {
        guard let screen = NSScreen.main else { return }
        let f = screen.visibleFrame
        panel.setFrameOrigin(NSPoint(
            x: f.midX - panel.frame.width / 2,
            y: f.minY + 96
        ))
    }
}
