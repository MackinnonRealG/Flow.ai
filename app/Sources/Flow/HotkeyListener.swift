import AppKit
import CoreGraphics

/// Watches for press/release of a single modifier key system-wide via a
/// listen-only CGEventTap. Requires the Input Monitoring permission.
final class HotkeyListener {
    /// Right Option. Left Option is 58; right Command is 54.
    private let keyCode: CGKeyCode = 61

    var onPress: (() -> Void)?
    var onRelease: (() -> Void)?

    private var eventTap: CFMachPort?
    private var isDown = false

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
        guard type == .flagsChanged,
              CGKeyCode(event.getIntegerValueField(.keyboardEventKeycode)) == keyCode
        else { return }

        let pressed = event.flags.contains(.maskAlternate)
        guard pressed != isDown else { return }
        isDown = pressed
        let action = pressed ? onPress : onRelease
        DispatchQueue.main.async { action?() }
    }
}
