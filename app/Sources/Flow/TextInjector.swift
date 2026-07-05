import AppKit

/// Types text into the frontmost app: put it on the pasteboard, synthesize
/// ⌘V, then restore whatever was on the pasteboard before. Requires the
/// Accessibility permission; without it we leave the text on the clipboard
/// so the user can paste manually.
final class TextInjector {
    var trusted: Bool { AXIsProcessTrusted() }

    /// Returns true if the text was auto-typed, false if only copied.
    @discardableResult
    func inject(_ text: String) -> Bool {
        let pb = NSPasteboard.general
        let saved = pb.string(forType: .string)
        pb.clearContents()
        pb.setString(text, forType: .string)

        guard trusted else { return false } // fallback: leave it on the clipboard

        let src = CGEventSource(stateID: .combinedSessionState)
        let vDown = CGEvent(keyboardEventSource: src, virtualKey: 9, keyDown: true) // 9 = V
        let vUp = CGEvent(keyboardEventSource: src, virtualKey: 9, keyDown: false)
        vDown?.flags = .maskCommand
        vUp?.flags = .maskCommand
        vDown?.post(tap: .cghidEventTap)
        vUp?.post(tap: .cghidEventTap)

        // restore the previous clipboard once the paste has landed
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
            pb.clearContents()
            if let saved { pb.setString(saved, forType: .string) }
        }
        return true
    }
}
