#!/usr/bin/env bash

set -ev

exec python -m ai_assistant.workers.deletion_worker
