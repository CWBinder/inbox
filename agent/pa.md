# Driving pa

`pa` is the assistant layer: it talks to the world on the person's behalf and
logs what it did. Use it instead of calling the whatsapp or email clients
directly; it picks the account or identity and applies the person's policy.

## Reading

```text
pa status                                   health of every account, bridge and timer
pa wa recent [--since 24h]                  WhatsApp, as the person
pa wa read WHO | search TEXT | download ID  any whatsapp subcommand passes through
pa email search QUERY [--account NAME]      any gmail subcommand passes through
pa email read ID [--thread]
pa email attachments ID --save DIR
pa remind list [--due-within 2d]            reminders plus due ws tasks
pa log [--since 7d]                         what was sent, saved or refused
```

Without `--account` the default mailbox is used. `pa status` lists the
accounts and identities that exist.

## Acting

Every side effect goes through policy. A refusal exits 3 and says why; do
not work around it and do not retry with different flags.

```text
pa wa send WHO --body TEXT --confirmed      only after the person approved this exact text
pa email draft --to X --subject S --body B  drafts are usually the ceiling
pa remind add TEXT --due WHEN [--ref K:V]   'fri 9am', 'tomorrow 18:30', 'in 2h'
pa remind done ID | snooze ID --until WHEN
```

`--confirmed` asserts that the person approved this recipient and this text
in this conversation. Never pass it on the strength of an earlier yes.
Sending email, trashing mail and deleting drafts are refused unless policy
says otherwise; report that rather than looking for another route.

## Refs on reminders

`--ref` takes kind-prefixed text: `ws:task:<key>`, `email:<account>:<id>`,
`whatsapp:<who>:<message-id>`, `url:...`, `file:...`. Put in whatever the
person will need when the reminder fires. pa prints them into the message.
