/**
 * Where the agent runs. A build made after `scripts/client-env.sh` (client/.env.production) talks to the runtime on
 * AWS and signs in with Cognito; a development build talks to `uv run radagent --serve --port 8787` on this machine
 * with no sign-in (client/.env.development). None of these values are secrets
 */
const env = import.meta.env;

export const region: string = env.VITE_AWS_REGION ?? "";
export const runtimeArn: string = env.VITE_RUNTIME_ARN ?? "";
export const cognitoClientId: string = env.VITE_COGNITO_CLIENT_ID ?? "";

/** True when the agent is on AWS, behind Cognito */
export const remote = Boolean(runtimeArn);

const localUrl: string = env.VITE_AGENT_URL ?? "ws://127.0.0.1:8787/ws";

/**
 * The agent's WebSocket. On AWS the session id routes every connection of this user, from any device, to the same
 * runtime session, so a reply started on the phone streams on the Mac too
 */
export function agentUrl(sessionId?: string): string {
  if (!remote) return localUrl;
  const base = `wss://bedrock-agentcore.${region}.amazonaws.com/runtimes/${encodeURIComponent(runtimeArn)}/ws`;
  return sessionId ? `${base}?X-Amzn-Bedrock-AgentCore-Runtime-Session-Id=${encodeURIComponent(sessionId)}` : base;
}
