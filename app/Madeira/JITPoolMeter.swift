// SPDX-License-Identifier: GPL-3.0-or-later
// Madeira Converter Exception: see LICENSE-EXCEPTION.md

import Foundation

/// The JIT pool's use for the performance overlay ("JIT 374/560 MB"), read from
/// the log lines the pool already writes: `JIT pool: RX=..., size=560MB` when it
/// is set up, and `[jit-pool] image ... used=0x../0x..` or
/// `[jit-pool] EXHAUSTED ... bump=0x../0x..` as code is loaded into it. Its size
/// changes from launch to launch (iPadOS decides how much contiguous space is free),
/// and a game that runs out of it stops: CS2 at the Valve logo on 2026-10-25 had
/// 560 MB of 896 MB and ran out loading v8.dll. LogStore feeds every line; the
/// overlay reads `text` once a second.
enum JITPoolMeter {
    struct State: Equatable {
        var sizeMB: Int?
        var used: UInt64 = 0
        var total: UInt64 = 0
        var exhausted = 0
        var shrunk = false
    }

    private static let lock = NSLock()
    private static var state = State()

    static func reset() { lock.lock(); state = State(); lock.unlock() }

    static var current: State { lock.lock(); defer { lock.unlock() }; return state }

    /// Cheap for lines that are not the pool's: one `contains` each.
    static func note(_ line: String) {
        guard line.contains("JIT pool: RX=") || line.contains("[jit-pool] ") || line.contains("no hole fits a ") else { return }
        lock.lock(); defer { lock.unlock() }
        state = next(state, line)
    }

    static func next(_ previous: State, _ line: String) -> State {
        var s = previous
        if line.contains("no hole fits a ") { s.shrunk = true }
        if let r = line.range(of: "JIT pool: RX="), let size = line[r.upperBound...].range(of: "size=") {
            s.sizeMB = Int(line[size.upperBound...].prefix { $0.isNumber })
        }
        if let r = line.range(of: "[jit-pool] ") {
            let rest = line[r.upperBound...]
            if let pair = hexPair(rest, after: "used=0x") ?? hexPair(rest, after: "bump=0x") {
                s.used = pair.0
                if pair.1 > 0 { s.total = pair.1 }
            }
            if rest.contains("EXHAUSTED") { s.exhausted += 1 }
        }
        return s
    }

    /// "JIT 374/560 MB", "JIT FULL 560 MB" once it ran out; nil before the pool is set up.
    static func text(_ s: State) -> String? {
        let totalMB = s.total > 0 ? Int((s.total + (1 << 19)) >> 20) : s.sizeMB
        guard let totalMB else { return nil }
        if s.exhausted > 0 { return "JIT FULL \(totalMB) MB" }
        return "JIT \(Int((s.used + (1 << 19)) >> 20))/\(totalMB) MB" + (s.shrunk ? " (small)" : "")
    }

    /// "used=0x78000/0x23000000" -> (0x78000, 0x23000000).
    static func hexPair(_ text: Substring, after marker: String) -> (UInt64, UInt64)? {
        guard let r = text.range(of: marker) else { return nil }
        let first = text[r.upperBound...].prefix { $0.isHexDigit }
        guard let a = UInt64(first, radix: 16) else { return nil }
        let rest = text[r.upperBound...].dropFirst(first.count)
        guard rest.hasPrefix("/0x") else { return (a, 0) }
        return (a, UInt64(rest.dropFirst(3).prefix { $0.isHexDigit }, radix: 16) ?? 0)
    }
}
