# pa

The assistant layer. `pa` talks to the world on one person's behalf: mail and
WhatsApp through standalone clients, reminders that reach their phone, a
policy on what may be sent, and a log of everything that was. It stores no
knowledge; that is the job of a store such as [ws](../ws), which pa uses
when present and does not need.

```
pa
├── knows   accounts, identities, who "me" is         ~/.pa/config.toml
├── decides what may be sent, by whom, to whom        ~/.pa/policy.toml
├── drives  whatsapp (any profile), gmail             clients on PATH
├── keeps   reminders with refs, and a launchd timer  ~/.pa/reminders/
└── logs    every send, save, download and refusal    ~/.pa/log/actions.jsonl
```

## Install

```bash
uv tool install -e .          # gives you `pa`
pa init                       # writes ~/.pa/config.toml and policy.toml from the examples
```

Edit both files. The clients pa drives must be on PATH: the
[whatsapp](../whatsapp) client for WhatsApp, the [gmail](../gmail-mcp) client
for mail. `pa status` tells you what is missing.

## Commands

```
pa status                                    every identity, account, bridge and timer in one check

pa wa [--as IDENTITY] SUBCOMMAND ...         whatsapp with the identity's profile; `whatsapp -h` for subcommands
pa wa send WHO --body TEXT [--confirmed]     policy-gated; logged
pa email [--account NAME] SUBCOMMAND ...     gmail with the account; add --confirmed for send

pa remind add TEXT --due WHEN [--ref K:V]... 'fri 9am', 'tomorrow 18:30', 'in 2h', '2026-09-12 16:00'
pa remind list [--due-within 2d] [--all]     your reminders plus due ws tasks
pa remind run [--dry-run]                    fire what is due; what the timer calls
pa remind done|snooze ID [--until WHEN]      ws tasks: done via ws edit, snooze via ws edit --due
pa remind install [--every 10]               launchd timer on this Mac
pa remind show ID

pa policy                                    the rules
pa log [--since 7d] [--json]                 the trail
```

## Policy

Levels `deny`, `draft-only`, `confirm`, `allow`; missing keys are the most
restrictive. `confirm` means the caller passes `--confirmed`, asserting the
person approved this exact recipient and text. An earlier yes never covers a
later message. Per identity, `allow_to = ["me"]` restricts recipients.

pa's policy is the gate. When it says yes, pa sets the whatsapp client's own
send switch for that one call, so the client's config can stay off.

## Reminders

A reminder is time, text, channel and refs. It is not a task. Refs are text
with a kind prefix (`ws:task:x`, `email:work:<id>`, `whatsapp:Alice:<id>`,
`url:...`, `file:...`); pa prints them into the message and follows a kind
only when the matching tool is installed. Reminders go out from the identity
named in `[reminders] identity` (default `claude`) to `[me].whatsapp`, so
they arrive as an incoming message from a second number and the phone
notifies. A message from your own number would not.

When `ws` is installed, its open tasks with a due date feed the same loop,
read only, each sent once per due date.

## Layout of ~/.pa

```
config.toml   accounts, identities, me
policy.toml   send and confirmation rules
reminders/    one JSON file per reminder
state/        ws-sent.json and other run markers
log/          actions.jsonl, remind-run.log
```

Private. Never commit it to a public repository.
