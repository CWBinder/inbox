# Getting started

From an empty machine to `inbox recent` in five steps. Needs Python 3.11 or
newer and [uv](https://docs.astral.sh/uv/); WhatsApp additionally needs Go,
Gmail needs Node.

## 1. Install inbox

```bash
git clone https://github.com/<you>/inbox ~/Projects/inbox
uv tool install -e ~/Projects/inbox
inbox init
```

`init` writes `~/.inbox/config.toml` and `~/.inbox/policy.toml` from the
examples. `inbox status` now runs and reports no channels. That is expected.

## 2. Install a connector and sign it in

A connector is a client command that talks to one service. Signing in is
the client's own procedure; inbox is not involved yet.

**WhatsApp**

```bash
git clone https://github.com/<you>/whatsapp ~/Projects/whatsapp
uv tool install -e ~/Projects/whatsapp/whatsapp-client
whatsapp bridge build
whatsapp bridge start        # prints a QR code: WhatsApp > Settings > Linked Devices > Link a Device
                             # wait until the history has loaded, then Ctrl-C
whatsapp bridge install      # a launchd agent keeps the bridge running from now on
whatsapp accounts            # ok: default   4412345678   linked, bridge running on 8080
```

**Gmail**

```bash
git clone https://github.com/<you>/gmail ~/Projects/gmail
uv tool install -e ~/Projects/gmail/gmail-client
```

Then follow the Gmail README, step 1: a Google Cloud project with the Gmail
API enabled and an OAuth desktop client, whose `credentials.json` goes into
the checkout. Then:

```bash
cd ~/Projects/gmail && npm install && npm run build && npm run auth    # browser sign-in, writes token.json
gmail accounts               # ok: default   you@example.org
```

A second mailbox is a subfolder with its own `credentials.json`, signed in
with `GMAIL_CREDENTIALS_PATH` and `GMAIL_TOKEN_PATH` pointing at it, and a
line in the checkout's `config.toml` naming it. The client's `config.example.toml`
shows the shape.

**Telegram**, the cheapest channel for reminders to yourself, since a bot
needs no phone number:

```bash
git clone https://github.com/<you>/telegram ~/Projects/telegram
uv tool install -e ~/Projects/telegram
# in Telegram: message @BotFather, /newbot, copy the token into config.toml (see config.example.toml)
# then open your bot and press Start; bots cannot write first
telegram contacts            # shows your chat id; put it in config.toml as `me = <id>`
telegram accounts            # ok: claude   @yourbot
```

Either way, the test is the same: `<client> accounts` lists at least one
account and says ok.

## 3. Declare your channels

A channel is your name for one account of one connector. The connector name
is the command's name; the account name is what `<client> accounts` printed.

```bash
inbox channel add me   --connector whatsapp --account default --default --address 4412345678
inbox channel add work --connector gmail    --account default --default
inbox channel add claude --connector telegram --account claude      # reminders go out from here
inbox status
```

`status` asks every connector about every channel. When every line says ok,
you are done. `--default` marks the channel used when `--via` is omitted for
that connector; `--address` is your own number, so that `me` works as a
recipient and reminders know where to go.

## 4. Decide what may be sent

Open `~/.inbox/policy.toml`. The example is a sensible start: every send
needs `--confirmed`, mail is draft-only, nothing destructive. Relax it per
channel when you want to.

## 5. Use it

```bash
inbox recent --since 24h --incoming        everything that came in, all channels
inbox search "invoice" --via work
inbox read "Jane"                          one person across channels
inbox draft jane@example.org --via work --subject Hi --body "..."
inbox send Jane --body "On my way" --confirmed
```

`inbox -h` lists the rest. `inbox wa ...` and `inbox email ...` reach a
connector's own commands with the account chosen for you.

## When something fails

- `inbox status` shows FAILED with a message from the connector. Sign that
  account in again with the client's own procedure; inbox never touches
  credentials.
- `refused: policy: ...` is inbox declining on purpose. Read
  `~/.inbox/policy.toml`; pass `--confirmed` only when a person approved
  this exact message.
- `unknown channel` means a typo or a missing `channel add`; `inbox channel
  list` shows what exists.
- `inbox connectors --check whatsapp` tests a client against the contract
  and names what is missing, which is where to look when a new or updated
  client misbehaves.

## Adding a service nobody has written a client for

Write a command that speaks [CONNECTORS.md](CONNECTORS.md): six verbs, one
JSON record, an account selector. Put it on PATH, run `inbox connectors
--check <name>` until it passes, add a channel. inbox needs no change.
