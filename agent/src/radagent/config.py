# Model configuration as per the Amazon Bedrock Model ID
MODEL: str = "global.anthropic.claude-sonnet-4-6"

# /research plans and writes its report on RESEARCH_MODEL, and its research agents run on RESEARCH_AGENT_MODEL, a
# fast model since they take many small steps; None uses the conversation's model
RESEARCH_MODEL: str | None = None
RESEARCH_AGENT_MODEL: str | None = "global.anthropic.claude-haiku-4-5-20251001-v1:0"

# Domains whose web content may lead the agent to run shell commands or change files (subdomains included)
# Reading anything outside this list disables shell, write and edit for the rest of the session
# Only list sites where nobody else can publish, e.g. "docs.python.org"; not github.com or wikipedia.org
TRUSTED_DOMAINS: tuple[str, ...] = ()
