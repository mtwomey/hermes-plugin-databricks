#!/usr/bin/env bash
# Thin launcher — delegates to setup.py under the Hermes venv Python.
# Do NOT hardcode paths or use #!/path/to/python shebang on setup.py —
# shebang lines don't expand ~ and break across users.
exec "$HOME/.hermes/hermes-agent/venv/bin/python3" "$(dirname "${BASH_SOURCE[0]}")/setup.py" "$@"
