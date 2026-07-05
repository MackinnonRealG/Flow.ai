import AppKit
import Carbon.HIToolbox

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

        // fallback: leave it on the clipboard when we can't or shouldn't type —
        // secure input (password fields) means paste would be silently eaten
        guard trusted, !IsSecureEventInputEnabled() else { return false }

        postKeystroke(virtualKey: 9, flags: .maskCommand) // ⌘V

        // restore the previous clipboard once the paste has landed
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
            pb.clearContents()
            if let saved { pb.setString(saved, forType: .string) }
        }
        return true
    }

    /// Copy the current selection in the frontmost app (⌘C) and return it.
    /// Restores the clipboard. Returns "" when nothing is selected.
    func captureSelection() -> String {
        guard trusted else { return "" }
        let pb = NSPasteboard.general
        let saved = pb.string(forType: .string)
        let before = pb.changeCount
        postKeystroke(virtualKey: 8, flags: .maskCommand) // ⌘C

        // wait briefly for the frontmost app to service the copy
        var selection = ""
        for _ in 0..<10 {
            usleep(30_000)
            if pb.changeCount != before {
                selection = pb.string(forType: .string) ?? ""
                break
            }
        }
        pb.clearContents()
        if let saved { pb.setString(saved, forType: .string) }
        return selection
    }

    private func postKeystroke(virtualKey: CGKeyCode, flags: CGEventFlags) {
        let src = CGEventSource(stateID: .combinedSessionState)
        let down = CGEvent(keyboardEventSource: src, virtualKey: virtualKey, keyDown: true)
        let up = CGEvent(keyboardEventSource: src, virtualKey: virtualKey, keyDown: false)
        down?.flags = flags
        up?.flags = flags
        down?.post(tap: .cghidEventTap)
        up?.post(tap: .cghidEventTap)
    }
}
