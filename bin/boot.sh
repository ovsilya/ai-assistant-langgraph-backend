#!/usr/bin/env bash

set -ev

BIN_ROOT=$(dirname "$0")

if [ "$ROLE" = "api" ]; then
  "$BIN_ROOT"/boot-api.sh
elif [ "$ROLE" = "deletion-worker" ]; then
  "$BIN_ROOT"/boot-deletion-worker.sh
else
  echo "I don't have any role and only exist to be extended so I'll just exit, thanks"
fi

