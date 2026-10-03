# Login shells in the sandbox (the agent's commands run in one): user-level installs land on PATH, and npm installs
# globally into the home directory, since the agent has no root
export PATH="$HOME/.local/bin:$HOME/.npm-global/bin:$HOME/.cargo/bin:$HOME/go/bin:$PATH"
export NPM_CONFIG_PREFIX="$HOME/.npm-global"
export UV_LINK_MODE=copy
export PYTHONDONTWRITEBYTECODE=1
