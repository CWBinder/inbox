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

## Chats: talking to sessions from your phone

`~/.inbox/chats.toml` names the conversations you can reach from the reminder
channel. A chat resumes a claude session, or starts fresh from a roster role.
One chat is current. On the phone:

```
chats            the list
talk NAME        switch; the bot answers "[NAME] talking to NAME"
new NAME         a fresh chat under that name
done             close the current chat (and its reminder, if it has one)
anything else    a prompt for the current chat; the answer comes back as [NAME] ...
```

From a terminal: `inbox chat list | add NAME [--session ID] [--role R] [--about ...] | expose NAME | remove NAME | say NAME TEXT`.
`inbox chat expose NAME --session ID` puts a session you are sitting in on the phone.

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
