#!/usr/bin/env bash
set -euo pipefail

mkdir -p ~/.local/bin
curl -L --fail -o /tmp/tectonic.tar.gz \
  https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%400.17.0/tectonic-0.17.0-x86_64-unknown-linux-musl.tar.gz
tar -xzf /tmp/tectonic.tar.gz -C ~/.local/bin
chmod +x ~/.local/bin/tectonic
rm /tmp/tectonic.tar.gz
~/.local/bin/tectonic --version
