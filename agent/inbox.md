# Driving inbox

`inbox` is the person's channels with rules: it drives the mail and chat
clients, picks the account, applies the sending policy, and logs what it did.
Use it instead of calling `gmail` or `whatsapp` directly.

Where: `--via CHANNEL` names one of the person's channels (`inbox channel
list`). Recipients: a channel name (`me`), a raw address, or a contact name.

## Reading

```text
inbox status                                  every channel and connector in one check
inbox recent [--since 24h] [--incoming]       what came in, all channels merged by time
inbox search QUERY [--via qmt,oxai] [-n 20]   the service's own query syntax (Gmail operators work)
inbox read WHO [-n 30]                        one person across channels
inbox read ID --via CHANNEL [--thread]        one message
inbox resolve WHO                             which channel and address a name maps to
inbox wa read WHO | inbox wa recent | inbox wa download ID     whatsapp's own commands
inbox email read ID --thread | inbox email attachments ID --save DIR   gmail's own commands
inbox remind list [--due-within 2d]           reminders plus due ws tasks
inbox log [--since 7d]                        what was sent, drafted, saved or refused
```

Pass-through groups take `--via CHANNEL` first: `inbox email --via oxai search "is:unread"`.
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

## Refs on reminders

`--ref` takes kind-prefixed text: `ws:task:<key>`, `email:<channel>:<id>`,
`whatsapp:<who>:<message-id>`, `url:...`, `file:...`. inbox prints them into
the message.
