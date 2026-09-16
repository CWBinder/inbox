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

## 3. Register connectors

After installing and authenticating each connector, run:

```bash
inbox connector add whatsapp
inbox connector add gmail
inbox connector add telegram
inbox channel list
inbox status
```

Inbox asks each executable for `capabilities` and `accounts --json`, then
writes its command mapping and channels into `~/.inbox/config.toml`. Each
channel is named `connector.account`. You do not choose another Inbox name.
For example:

```text
whatsapp + default → whatsapp.default
gmail + work       → gmail.work
telegram + claude  → telegram.claude
```

These account names are examples: use the channels printed by registration.
If the WhatsApp connector reports `default`, its channel is `whatsapp.default`;
getting `whatsapp.me` requires an account named `me` in the connector itself.

```bash
inbox search "invoice" --via gmail.work
inbox send Jane --via whatsapp.default --body "On my way" --confirmed
inbox draft jane@example.org --via gmail.work --subject Hi --body "..."
```

Registration copies each account's address and default flag when first creating
its channel; a single account becomes default automatically. Existing defaults
are preserved. With multiple accounts and no default, pass `--via` explicitly.

Run the same registration command after adding another account to a connector.
It adds newly discovered accounts and preserves existing settings and legacy
channel names. Accounts reported as unavailable are also registered, with a
warning to check their authentication or connector status. Malformed discovery
responses and conflicting mappings fail without changing configuration.

Registration does not configure reminder delivery. If using a Telegram bot,
set `[reminders]` in `~/.inbox/config.toml` to its registered channel and a
recipient address recognized by that connector. See [REMINDERS.md](REMINDERS.md).

## 4. Decide what may be sent

Open `~/.inbox/policy.toml`. The example is a sensible start: every send
needs `--confirmed`, the example Gmail work/personal channels are draft-only,
and destructive operations are denied. Relax it per
channel when you want to.

## 5. Use it

```bash
inbox recent --since 24h --incoming        everything that came in, all channels
inbox search "invoice" --via gmail.work
inbox read "Jane"                          one person across channels
inbox draft jane@example.org --via gmail.work --subject Hi --body "..."
inbox send Jane --body "On my way" --confirmed
```

`inbox -h` lists the rest. For connector-specific commands, use
`inbox gmail --via gmail.work SUBCOMMAND` (or another registered connector).

## When something fails

- `inbox status` shows FAILED with a message from the connector. Sign that
  account in again with the client's own procedure; inbox never touches
  credentials.
- `refused: policy: ...` is inbox declining on purpose. Read
  `~/.inbox/policy.toml`; pass `--confirmed` only when a person approved
  this exact message.
- `unknown channel` means a typo or a missing `connector add`; `inbox channel
  list` shows what exists.
- `inbox connectors --check whatsapp` tests a client against the contract
  and names what is missing, which is where to look when a new or updated
  client misbehaves.

## Adding a service nobody has written a client for

Write an executable that follows [CONNECTORS.md](CONNECTORS.md). If it is
called `matrix-cli` and reports connector `matrix` and account `personal`:

```bash
inbox connector add matrix-cli
inbox connectors --check matrix
inbox search "project update" --via matrix.personal
```

You can also pass the executable's full path. Registration records its resolved
path, so the executable name can differ from the reported connector name.
The connector owns authentication and account naming. Inbox needs no
service-specific code. Connector and account names must start with a lowercase
letter and contain only lowercase letters, digits, hyphens, or underscores.

For existing installations, custom channel names continue to work. The manual
`inbox channel add NAME --connector CONNECTOR --account ACCOUNT` command remains
available, but is no longer needed for normal setup.

## Updating Inbox

Keep the checkout in place. To update the code and rebuild its local
environment:

```bash
cd ~/Projects/inbox
git pull --ff-only
python3 install.py
inbox status
```
