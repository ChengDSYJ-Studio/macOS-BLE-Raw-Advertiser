#!/bin/bash
exec "$(cd "$(dirname "$0")" && pwd -P)/scripts/control.sh" stop "$@"
