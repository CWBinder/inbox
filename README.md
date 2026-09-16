# inbox

Your channels, with rules. `inbox` drives the mail and chat clients you
already have (connectors), gives you one merged view across them, applies a
policy on what may be sent from where, fires reminders that reach your
phone, and logs everything it did. It stores no knowledge; that is the job
of a store such as [ws](../ws), which inbox uses when present and does not
need.

```
inbox
├── channels    your names for one account of one connector      ~/.inbox/config.toml
├── policy      what may be sent, from which channel, to whom    ~/.inbox/policy.toml
├── connectors  gmail, whatsapp, telegram, ... any command on PATH that speaks CONNECTORS.md
├── reminders   time + text + refs, sent from a second number     ~/.inbox/reminders/
└── log         every send, draft, download and refusal           ~/.inbox/log/actions.jsonl
```

## Install

The full walk from an empty machine, connectors and sign-in included, is
[GETTING-STARTED.md](GETTING-STARTED.md). In short:

```bash
git clone https://github.com/CWBinder/inbox.git ~/Projects/inbox
cd ~/Projects/inbox
python3 install.py
inbox init                    # writes ~/.inbox/config.toml and policy.toml from the examples
```

The installer creates `.venv/` inside this checkout, installs Inbox there in
editable mode, and links `~/.local/bin/inbox` to `.venv/bin/inbox`. You do not
activate the environment for normal use. Keep the checkout in place; the
installed command uses its source code. If `~/.local/bin` is not on `PATH`, add
`export PATH="$HOME/.local/bin:$PATH"` to your shell configuration.

Install the connector CLIs you want on `PATH`: for example [gmail](../gmail),
[whatsapp](../whatsapp), and [telegram](../telegram). A connector is the
software; an account is one login or bot known to that software; a channel is
automatically named `connector.account`:

```text
gmail.work          → gmail connector → work account
whatsapp.default    → whatsapp connector → default account
telegram.assistant  → telegram connector → assistant account
```

Register an installed, configured connector with one command:

```bash
inbox connector add gmail
inbox connector add whatsapp
inbox status                  # every channel checked through its connector
```

Inbox reads `capabilities` and `accounts --json`, validates the discovery
responses, and saves the executable and every account in `~/.inbox/config.toml`.
For a Slack connector reporting account `qmt`, use `--via slack.qmt`. If its
executable is called `my-slack-cli`, register with `inbox connector add my-slack-cli`;
the reported connector name still determines `slack.qmt`.

Re-running registration adds newly discovered accounts and preserves existing
settings. Unavailable accounts are registered with a status warning. An account's
reported address and default status are copied when first registered; a sole
account becomes default. Existing defaults take precedence. Existing custom names
remain usable, and their sending restrictions are inherited by the new canonical
names. `inbox channel add` remains available for manual configuration.

## Vocabulary

- **connector**: a client command that talks to one service and speaks the
  contract in [CONNECTORS.md](CONNECTORS.md). `inbox connector add EXECUTABLE`
  discovers its accounts. `inbox connectors --check NAME` tests one.
- **account**: the connector's own name for one set of credentials
  (`gmail accounts`, `whatsapp accounts`).
- **channel**: one connector account, named `connector.account`:
  `--via gmail.work`, `--via telegram.assistant`.

## Commands

```
inbox recent [--since 24h] [--incoming] [--via a,b]   what came in, all channels merged by time
inbox threads [QUERY] [--via a,b] [--from] [--since]  find readable email chains, chats and channels
inbox search QUERY [--via a,b] [--thread] [--from]    find messages; bare text searches visible content
inbox read WHO [-n 30]                                one person across channels
inbox read --message ID --via CHANNEL                 one exact message
inbox read --thread ID --via CHANNEL                  one complete thread
inbox resolve WHO                                     which channel and address a recipient maps to

inbox send WHO [--via CH] --body TEXT [--reply-to ID] [--attach FILE] [--confirmed] [connector flags]
inbox draft WHO [--via CH] --body TEXT ...            on channels that have drafts

inbox gmail    [--via CH] SUB ...                     a connector's own commands, account chosen for you
inbox whatsapp [--via CH] SUB ...                     (optional aliases can be set in config)

inbox remind add TEXT --due WHEN [--ref K:V]...       'fri 9am', 'tomorrow 18:30', 'in 2h'
inbox remind list [--due-within 2d] | run [--dry-run] | done ID | snooze ID --until WHEN
inbox remind install [--every 10]                     launchd timer on this Mac

inbox remote list                                     what your phone can reach
inbox remote expose agent ROLE [--name NAME]
inbox remote expose conversation NAME [--backend B --session ID --cwd DIR]
inbox remote hide agent NAME-OR-ROLE
inbox remote hide conversation NAME

inbox status | connectors | channel list | policy | log [--since 7d]
inbox connector add EXECUTABLE                        register discovered connector.account channels
```

Recipients are a channel name (`me`), a raw address (`x@y.org`, `4366...`),
or a contact name, which is asked of each connector's `resolve`. An email
address goes by mail, a number by chat, on that connector's default channel
unless `--via` says otherwise. Flags inbox does not know are passed to the
connector untouched, so `--subject` and `--cc` reach gmail.

Every returned message has an opaque, self-contained `id` and an opaque
`thread` id. A message id identifies one message within its connector account;
a thread id identifies an independently readable email chain, chat, channel,
or reply thread. Get thread ids from `inbox threads` or any search result.
Use `search --thread ID` to search within one thread. `--native` enables a
connector's advanced service syntax, such as Gmail search operators.
“Thread” is the contract word even when the service calls the same object a
chat, channel, or conversation.

## Policy

Levels `deny`, `draft-only`, `confirm`, `allow`, per channel, with
`[defaults]` underneath and the most restrictive level as the floor.
`confirm` means the caller passes `--confirmed`, asserting the person
approved this exact recipient and text; an earlier yes never covers a later
message. `allow_to = ["me"]` restricts a channel to named recipients. When
policy says yes, inbox lifts the connector's own send guard for that one
call.

## Remote access: agents and conversations on your phone

Send `chats` for one menu with two blocks:

- **Agents — start a new conversation.** Only agents you explicitly expose.
- **Conversations — resume where you left off.** Only conversations you save
  or expose, plus reminder conversations made available when announced.

`talk NAME` selects an entry; your next message tells the agent what to do.
Choosing an agent **always starts fresh**, even if you previously talked to
that agent. Choosing a conversation continues its saved session. An agent is
addressable by both its friendly name and its roster role: an exposed `Emma`
with role `email` responds to both `talk Emma` and `talk email`. Agent names,
role aliases and conversation names cannot overlap; matching ignores case.
An exposed reminder or conversation with no session yet is marked “not started”.

```
chats            agents and conversations in two blocks
talk NAME       select an agent or conversation, then send your message
save NAME        name and expose the current conversation for later
leave [NAME]     stop routing messages; keep the conversation exposed
remove NAME      remove its Inbox mapping; keep backend history intact
anything else    a prompt for the current conversation
```

`available`, `available chats`, `agents`, `roles`, and `who` are aliases for
`chats`. `new NAME` creates a generic conversation without an agent role.
`leave` clears the current selection; `leave NAME` does the same only when
NAME is currently selected. It does not hide, remove or complete anything.
`remove NAME` explicitly removes that conversation from Inbox and clears the
selection when necessary. It does not delete Claude or Codex history or mark
a linked reminder complete. The retired exact command `done` explains these
choices instead of changing state.

For example: `talk librarian`, discuss a paper, then `save Readout papers`.
Later, `talk Readout papers` continues that conversation. `talk librarian`
always starts a new one. New conversations receive a temporary name such as
“librarian 1” and stay out of the menu until you save them. Switching chats
retains their local session records. Saving preserves the history and reminder
link and refuses to overwrite another saved name.

### Configuring remote access

The `remote` command is the Mac-side configuration interface. Expose only the
roles and conversations you want available on the phone:

```bash
roster list roles
inbox remote expose agent email --name Emma --about "Email help"
inbox remote expose agent logistics --about "Messages and coordination"
inbox remote list
inbox remote hide agent Emma                    # friendly name works
inbox remote hide agent email                   # roster role works too
```

`--name` and `--about` are optional. Agent exposure is stored in
`~/.inbox/agents.toml`; no roster role is exposed by default. Instructions
come from the installed prompt when available, otherwise the roster definition.
Hiding an agent leaves its saved conversations usable. Re-exposing a role with
a new friendly name renames that one remote entry rather than creating a second
entry for the same role.

### Exposing conversations

On the phone, `save NAME` exposes the current conversation. From an existing
agent session on the Mac, run:

```bash
inbox remote expose conversation "Inbox Chat" --about "Telegram and reminder design"
```

Inbox detects `CODEX_THREAD_ID` or `CLAUDE_SESSION_ID` and records the working
folder. If neither is available, specify `--backend codex --session ID` (or
`--backend claude --session ID`) on the Mac. `--cwd DIR` supplies a different
folder. You can also ask the agent in the desired conversation to expose it
under a short name. IDs never need to be typed on the phone.

```bash
inbox remote hide conversation "Inbox Chat"    # hide, retain the session
inbox remote expose conversation "Inbox Chat"  # re-expose the stored session
inbox remote list                               # preview the phone menu locally
```

Names and session IDs live in `~/.inbox/chats.toml`. Existing saved entries
remain exposed. Exposing refuses to replace a different session under an
existing name. Reminder notifications re-expose their linked conversation.
The older `inbox agent` and `inbox chat` commands remain as compatibility and
terminal-operation commands. `inbox chat remove NAME` removes an Inbox
registration without deleting the backend's conversation history.

Every message starts a new CLI process which resumes the saved conversation.
Claude role chats still use Claude; exposed Codex conversations use
`codex exec resume` with the existing account and permission configuration.
Codex's final response is returned to the phone. Desktop-only tools are not
guaranteed to be available in the CLI. Use one interface at a time for a
given session to avoid simultaneous turns against the same history.

## Reminders

The full model is in [REMINDERS.md](REMINDERS.md). A reminder is a Markdown
file with a due time, refs, watches, an optional role and a brief. The pass
runs on a timer and tells you on the reminder channel when one is due or a
watch fired. A reminder with a role is also a chat of the same name, so
`talk ID` works the moment it is announced; a plain reminder is only a poke.
`snooze ID 2h` from the phone pushes one.

```
inbox remind add TEXT --due WHEN [--ref K:V] [--watch K:V] [--role R]
inbox remind new TEXT --due WHEN ...          the brief template, opened in $EDITOR
inbox remind list | show ID | check ID | done ID | snooze ID --until WHEN
inbox remind say ID TEXT                      one turn with its chat, from the terminal
inbox remind run [--dry-run] | install [--every 10]
```

Local data stays private. `~/.inbox` never goes into the repository.
