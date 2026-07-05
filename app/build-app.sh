#!/bin/bash
# Build the Flow menu-bar app into app/Flow.app
set -euo pipefail
cd "$(dirname "$0")"

# Direct swiftc build — the CLT's SwiftPM ManifestAPI is broken on this
# machine (mismatched libPackageDescription), and we have no dependencies yet.
# Swift 5 language mode: AppKit callback patterns here predate strict concurrency.
mkdir -p .build
swiftc -O -swift-version 5 Sources/Flow/*.swift -o .build/Flow

rm -rf Flow.app
mkdir -p Flow.app/Contents/MacOS
cp .build/Flow Flow.app/Contents/MacOS/Flow
cp Info.plist Flow.app/Contents/Info.plist

# Ad-hoc sign so macOS TCC permissions (mic, input monitoring) stick to a
# stable identity across rebuilds.
codesign --force -s - Flow.app

echo "Built $(pwd)/Flow.app"
echo "Launch with: open $(pwd)/Flow.app"
