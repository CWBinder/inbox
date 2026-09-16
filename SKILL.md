---
name: inbox
description: Read, search and send across a person's mail and chat channels with their sending policy applied; reminders and a log. Use for any message work instead of calling gmail or whatsapp directly.
---

# Driving inbox

`inbox` is the person's channels with rules: it drives the mail and chat
clients, picks the account, applies the sending policy, and logs what it did.
Use it instead of calling `gmail` or `whatsapp` directly.

Where: `--via CHANNEL` names one of the person's channels (`inbox channel
list`). Canonical names are `connector.account`, such as `gmail.work`.
Recipients: a channel name, a raw address, or a contact name.

## Registering connectors

After installing and authenticating a connector, run `inbox connector add EXECUTABLE`.
Inbox obtains the connector name from `capabilities` and account names from
`accounts --json`, validates them, and registers every `connector.account` channel.
The executable can be on PATH or specified by its full path. Re-run registration
to discover new accounts. Use `inbox channel list` for exact names and `inbox status`
for account health. Credentials stay with the connector. Existing custom channel
names remain supported; their policies are inherited by canonical names.

## Reading

```text
inbox status                                  every channel and connector in one check
inbox recent [--since 24h] [--incoming]       what came in, all channels merged by time
inbox search QUERY [--via gmail.work,gmail.personal] [-n 20]   the service's own query syntax
inbox read WHO [-n 30]                        one person across channels
inbox read ID --via CHANNEL [--thread]        one message
inbox resolve WHO                             which channel and address a name maps to
inbox whatsapp read WHO | inbox whatsapp recent | inbox whatsapp download ID
inbox gmail read ID --thread | inbox gmail attachments ID --save DIR
inbox remind list [--due-within 2d]           reminders plus due ws tasks
inbox log [--since 7d]                        what was sent, drafted, saved or refused
```

Pass-through groups take `--via CHANNEL` first: `inbox gmail --via gmail.work search "is:unread"`.
Without it the connector's default channel is used. Name the channel in every report.

## Acting

Every side effect goes through policy. A refusal exits 3 and says why; do
not work around it and do not retry with different flags.

```text
inbox draft WHO --via CHANNEL [--subject S] --body TEXT [--reply-to ID] [--attach FILE]
inbox send WHO [--via CHANNEL] --body TEXT --confirmed        only after the person approved this exact text
inbox remind add TEXT --due WHEN [--ref KIND:VALUE]          'fri 9am', 'tomorrow 18:30', 'in 2h'
inbox remind done ID | snooze ID --until WHEN
```

`--confirmed` asserts that the person approved this recipient and this text
in this conversation. Never pass it on the strength of an earlier yes.
Sending mail, trashing mail and deleting drafts are refused by the usual
policy; report that rather than looking for another route. When the person
approves a draft, hand them the client command to send it themselves.

## Remote phone access

`remote` controls which fresh agents and resumable conversations are visible
through the person's configured phone channel. A friendly agent name and its
roster role are equivalent selectors.

```text
inbox remote list
inbox remote expose agent ROLE [--name NAME] [--about TEXT]
inbox remote expose conversation NAME [--backend codex|claude --session ID --cwd DIR]
inbox remote hide agent NAME-OR-ROLE
inbox remote hide conversation NAME
```

## Refs on reminders

`--ref` takes kind-prefixed text: `ws:task:<key>`, `email:<channel>:<id>`,
`whatsapp:<who>:<message-id>`, `url:...`, `file:...`. inbox prints them into
the message.
