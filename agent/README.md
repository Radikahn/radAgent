# radagent

A Python Strands agent baseline that is meant to be modded.

```sh
uv sync
uv run radagent --repl                 # chat in the terminal
uv run radagent --dev                  # serve the app over a WebSocket on 127.0.0.1:8787
```

`--serve` speaks AgentCore Runtime's contract (`/ws`, `/ping`, `/invocations`; see `src/radagent/server/app.py`).
The `Dockerfile` builds the linux/arm64 image the runtime runs, which serves on port 8080; `scripts/deploy-agent.sh`
builds, pushes and deploys it.

## Spotify

The `spotify_*` tools search Spotify, read the library, control playback and edit playlists as you. They act
through a Spotify app of your own, in Development Mode, which needs Spotify Premium on the account that owns it:

1. Create an app at <https://developer.spotify.com/dashboard> with the Web API, and add
   `http://127.0.0.1:8888/callback` to its Redirect URIs (Spotify takes `127.0.0.1`, not `localhost`).
2. Put its `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` in `agent/.env`.
3. `uv run radagent --spotify-login` opens Spotify's consent page and saves `SPOTIFY_REFRESH_TOKEN` to `agent/.env`.
   Set `SPOTIFY_REDIRECT_URI` if port 8888 is taken (and register that URI instead).
4. For the deployed agent, `scripts/put-secrets.sh`; new chats pick the keys up.

Spotify logins last 6 months; when one runs out the tools say so, and steps 3 and 4 renew it. Development Mode also
caps search at 10 results per type and only lists the songs of playlists you own or collaborate on. Spotify results
count as untrusted web content (playlist names and descriptions are anyone's to write), so like YouTube searches they
switch off shell and file editing for the rest of the chat.

## Google

The `google_*` tools search and read Google Drive (Docs come back as Markdown, Sheets as CSV, PDFs as text), write
and edit Google Docs, organize Drive, and read and change Google Calendar, as you. You connect them from the app:
Settings > Connections > Google > Connect opens Google's consent page in the browser, and Google sends it back to the
app, which hands the agent the authorization code. The agent trades it for a refresh token and keeps it
(`.agent/google.json` locally; on AWS the `radagent/google` secret, which only the agent's role can write), so the
tools work from any device. Disconnect in the same place revokes it.

It acts through a Google OAuth client of your own:

1. In the [Google Cloud console](https://console.cloud.google.com/), create a project and enable the **Google Drive
   API**, **Google Docs API** and **Google Calendar API** (and the Sheets and Slides APIs if you want `google_api` to
   reach them).
2. Google Auth Platform > Branding: name the app and give your email. Audience: External, then **Publish app**
   (to "In production"). In Testing, Google ends logins with these scopes after 7 days. A personal app needs no
   verification: the consent page warns that Google hasn't verified it (Advanced > Go to ...).
3. Clients > Create client > **iOS**, with bundle ID `com.radman.radagent`. Its client ID
   (`<id>.apps.googleusercontent.com`) is all the setup needs; iOS clients have no secret, and the app uses PKCE
   instead. The same client serves the Mac app.
4. For the deployed agent, put it in `infra/terraform.tfvars` as `google_client_id`, run `terraform apply`, deploy the
   agent, then `scripts/client-env.sh` and `scripts/install-mac.sh` / `scripts/install-ios.sh`. The install scripts
   register the client's redirect scheme (`com.googleusercontent.apps.<id>`) with the app
   (`scripts/tauri-config.sh`).
5. For development, put it in `client/.env.development.local` as `VITE_GOOGLE_CLIENT_ID` (and, optionally, in
   `agent/.env` as `GOOGLE_CLIENT_ID`, the only client the agent then accepts). `bun tauri dev` on a Mac can't catch
   Google's redirect, so after consenting, copy the address the browser couldn't open into the box Settings shows.

Untick nothing on the consent page: a tool whose scope is missing says so, and Settings offers to connect again.
Drive files can be shared with you by anyone and calendar invites can come from anyone, so like Spotify and YouTube
results, what the Google tools read counts as untrusted: it switches off shell and file editing for the rest of the
chat. In such a chat the Google tools also hold back what such content could use against you: raw `google_api`
changes (the way to share a file or delete one for good), and writing into files, folders or calendars someone else
owns. Reading, and creating, editing and trashing your own things, keep working; Drive's trash, Calendar's trash and
Docs' version history can undo those.

## Sandbox

The `sandbox_*` tools run commands, manage background jobs, edit files and move files to and from a container on your
own server, over SSH with asyncssh (`src/radagent/tools/sandbox`). They read `SANDBOX_HOST`, `SANDBOX_PORT`,
`SANDBOX_HOST_KEY`, `SANDBOX_SSH_KEY_PATH` (or `SANDBOX_SSH_KEY`) and, through a Cloudflare Tunnel,
`SANDBOX_CF_ACCESS_CLIENT_ID` and `SANDBOX_CF_ACCESS_CLIENT_SECRET`; `../sandbox/keygen.sh` makes the key and prints
the rest. Setting up the server is in [../sandbox/README.md](../sandbox/README.md). Like `shell`, the tools turn off for
the rest of a chat once it reads untrusted web content.
