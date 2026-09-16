# Getting started

From an empty machine to `inbox recent` in five steps. Inbox needs Git and
Python 3.11 or newer, including Python's `venv` support. WhatsApp additionally
needs Go and Gmail needs Node. Connectors are separate projects and may have
their own installation requirements. Their examples below use each connector's
current project-specific installer; Inbox itself does not depend on `uv`.

## 1. Install inbox

```bash
git clone https://github.com/CWBinder/inbox.git ~/Projects/inbox
cd ~/Projects/inbox
python3 install.py
inbox init
```

The installer creates `~/Projects/inbox/.venv`, installs Inbox into it in
editable mode, and links `~/.local/bin/inbox` to its command. You do not need
to activate the environment. If `inbox` is not found, add
`export PATH="$HOME/.local/bin:$PATH"` to your shell configuration and open a
new terminal.

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

In every case, the test is the same: `<client> accounts` lists at least one
account and says ok.

## 3. Declare your channels

This is the only registration step inside Inbox. Keep these three things
separate:

```text
connector   installed program that knows how to speak to a service
account     one login, profile or bot configured inside that program
channel     your Inbox name for one connector + account pair
```

For example, suppose the connector commands report:

```text
whatsapp accounts  → account: default
gmail accounts     → account: default
telegram accounts  → account: claude
```

Create one channel for each account you want Inbox to use:

```bash
inbox channel add me   --connector whatsapp --account default --default --address 4412345678
inbox channel add work --connector gmail    --account default --default
inbox channel add claude --connector telegram --account claude      # reminders go out from here
inbox status
```

These commands write mappings equivalent to:

```toml
[channels.me]
connector = "whatsapp"
account = "default"
default = true
address = "4412345678"

[channels.work]
connector = "gmail"
account = "default"
default = true
```

There is no separate `connector add`: using a connector in a channel makes it
known to Inbox. By default its connector name is also its executable name, so
`connector = "gmail"` means Inbox runs the `gmail` command on `PATH`.

`--default` applies within one connector. It lets `inbox email search ...` use
`work` when `--via work` is omitted. `--address` records your own address on
that service, allowing the channel name itself (`me`) to be resolved as a
recipient. `status` asks every connector about every declared account; when
every line says `ok`, setup is complete.

You now use the channel name with the shared commands:

```bash
inbox search "invoice" --via work
inbox send Jane --via me --body "On my way" --confirmed
inbox draft jane@example.org --via work --subject Hi --body "..."
```

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
JSON record, an account selector. If the new executable is called `matrix`:

```bash
matrix accounts
inbox connectors --check matrix
inbox channel add matrix-personal --connector matrix --account default --default
inbox status
```

Inbox now knows `matrix` because the `matrix-personal` channel uses it. If the
executable has a different name, or you want a short pass-through alias, add a
connector block to `~/.inbox/config.toml` before adding the channel:

```toml
[connectors.matrix]
command = "matrix-cli"
alias = "mx"
```

Then `inbox matrix ...` and `inbox mx ...` both run `matrix-cli` with the
account selected by `--via`. Inbox itself needs no service-specific code.

## Updating Inbox

Keep the checkout in place. To update the code and rebuild its local
environment:

```bash
cd ~/Projects/inbox
git pull --ff-only
python3 install.py
inbox status
```
