import AppKit
import CoreGraphics

enum HotkeyKind {
    case dictate  // Right ⌥ — hold to talk, double-tap to lock hands-free
    case command  // Right ⌘ — hold to speak an edit for the selected text
}

/// Watches for press/release of Flow's modifier hotkeys system-wide via a
/// listen-only CGEventTap. Requires the Input Monitoring permission.
final class HotkeyListener {
    /// keycode → (kind, the modifier flag that reflects its state)
    private let keys: [CGKeyCode: (kind: HotkeyKind, flag: CGEventFlags)] = [
        61: (.dictate, .maskAlternate),  // right Option
        54: (.command, .maskCommand),    // right Command
    ]

    var onPress: ((HotkeyKind) -> Void)?
    var onRelease: ((HotkeyKind) -> Void)?

    private var eventTap: CFMachPort?
    private var isDown: Set<CGKeyCode> = []

    /// Returns false if the tap could not be created (permission missing).
    func start() -> Bool {
        let mask = CGEventMask(1 << CGEventType.flagsChanged.rawValue)
        let callback: CGEventTapCallBack = { _, type, event, refcon in
            let listener = Unmanaged<HotkeyListener>.fromOpaque(refcon!).takeUnretainedValue()
            listener.handle(type: type, event: event)
            return Unmanaged.passUnretained(event)
        }
        guard let tap = CGEvent.tapCreate(
            tap: .cgSessionEventTap,
            place: .headInsertEventTap,
            options: .listenOnly,
            eventsOfInterest: mask,
            callback: callback,
            userInfo: Unmanaged.passUnretained(self).toOpaque()
        ) else { return false }

        eventTap = tap
        let source = CFMachPortCreateRunLoopSource(kCFAllocatorDefault, tap, 0)
        CFRunLoopAddSource(CFRunLoopGetMain(), source, .commonModes)
        CGEvent.tapEnable(tap: tap, enable: true)
        return true
    }

    private func handle(type: CGEventType, event: CGEvent) {
        // macOS disables taps that stall; re-enable defensively.
        if type == .tapDisabledByTimeout || type == .tapDisabledByUserInput {
            if let tap = eventTap { CGEvent.tapEnable(tap: tap, enable: true) }
            return
        }
        guard type == .flagsChanged else { return }
        let code = CGKeyCode(event.getIntegerValueField(.keyboardEventKeycode))
        guard let (kind, flag) = keys[code] else { return }

        let pressed = event.flags.contains(flag)
        if pressed && !isDown.contains(code) {
            isDown.insert(code)
            DispatchQueue.main.async { self.onPress?(kind) }
        } else if !pressed && isDown.contains(code) {
            isDown.remove(code)
            DispatchQueue.main.async { self.onRelease?(kind) }
        }
    }
}
