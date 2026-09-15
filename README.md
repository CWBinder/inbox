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
uv tool install -e .
inbox init                    # writes ~/.inbox/config.toml and policy.toml from the examples
```

Install the connectors you want on PATH: the [gmail](../gmail) client, the
[whatsapp](../whatsapp) client. Then declare your channels, one per account:

```bash
inbox channel add work --connector gmail --account work --default
inbox channel add me   --connector whatsapp --account default --default --address 4412345678
inbox status                  # every channel checked through its connector
```

## Vocabulary

- **connector**: a client command that talks to one service and speaks the
  contract in [CONNECTORS.md](CONNECTORS.md). Conformance is membership;
  nothing is registered. `inbox connectors --check NAME` tests one.
- **account**: the connector's own name for one set of credentials
  (`gmail accounts`, `whatsapp accounts`).
- **channel**: your name for one account of one connector. The only thing
  you type to say where: `--via qmt`, `--via claude`.

## Commands

```
inbox recent [--since 24h] [--incoming] [--via a,b]   what came in, all channels merged by time
inbox search QUERY [--via a,b] [--since] [-n]         the service's own query syntax
inbox read WHO [-n 30]                                one person across channels
inbox read ID --via CHANNEL [--thread]                one message
inbox resolve WHO                                     which channel and address a recipient maps to

inbox send WHO [--via CH] --body TEXT [--reply-to ID] [--attach FILE] [--confirmed] [connector flags]
inbox draft WHO [--via CH] --body TEXT ...            on channels that have drafts

inbox email [--via CH] SUB ...                        a connector's own commands, account chosen for you
inbox wa    [--via CH] SUB ...                        (aliases from config; the connector's name works too)

inbox remind add TEXT --due WHEN [--ref K:V]...       'fri 9am', 'tomorrow 18:30', 'in 2h'
inbox remind list [--due-within 2d] | run [--dry-run] | done ID | snooze ID --until WHEN
inbox remind install [--every 10]                     launchd timer on this Mac

inbox remote list                                     what your phone can reach
inbox remote expose agent ROLE [--name NAME]
inbox remote expose conversation NAME [--backend B --session ID --cwd DIR]
inbox remote hide agent NAME-OR-ROLE
inbox remote hide conversation NAME

inbox status | connectors | channel list | policy | log [--since 7d]
```

Recipients are a channel name (`me`), a raw address (`x@y.org`, `4366...`),
or a contact name, which is asked of each connector's `resolve`. An email
address goes by mail, a number by chat, on that connector's default channel
unless `--via` says otherwise. Flags inbox does not know are passed to the
connector untouched, so `--subject` and `--cc` reach gmail.

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
done             close the current conversation and its linked reminder
anything else    a prompt for the current conversation
```

`available`, `available chats`, `agents`, `roles`, and `who` are aliases for
`chats`. `new NAME` creates a generic conversation without an agent role.

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

Private. `~/.inbox` never goes into a public repository.
