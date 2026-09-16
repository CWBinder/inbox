# The connector contract

A connector is a command on PATH that talks to one messaging service and
speaks the verbs below. inbox never imports it: it builds a command line from
a channel's connector and account, runs it, and parses the JSON. Any language
qualifies. `inbox connector add EXECUTABLE` discovers and registers its accounts.

Two existing connectors are the reference: the [whatsapp](../whatsapp) and
[gmail](../gmail) clients. `inbox connectors --check NAME` runs this contract
against an installed connector and reports what is missing.

## Automatic registration

Install and authenticate the connector first, then register its executable:

```bash
inbox connector add matrix-cli
```

Inbox resolves the executable on PATH (or accepts its full path), invokes
`capabilities` and `accounts --json`, and records the resolved executable path.
If these report connector `matrix` and account `personal`, it writes:

```toml
[connectors.matrix]
command = "/path/to/matrix-cli"

[channels."matrix.personal"]
connector = "matrix"
account = "personal"
```

Names must start with a lowercase letter and contain only lowercase letters,
digits, hyphens or underscores. Dots separate connector and account names;
they cannot occur within either identifier. Connector names cannot collide with
Inbox commands or other connectors' aliases. Names come from the connector;
Inbox never silently lowercases or renames an account.

After registration:

```bash
inbox search "project update" --via matrix.personal
inbox matrix --via matrix.personal contacts
```

Registration validates required operations, the account flag and its position,
unique account names, and boolean account status/default fields. Empty or malformed
discovery results and conflicting mappings leave configuration unchanged. Discovery
has a 30-second timeout per command and does not send or read messages. It is not
a full end-to-end conformance test; `inbox connectors --check NAME` adds read checks.

Every discovered account is registered, including unavailable ones, whose status
is printed. `accounts --json` may exit 1 with a valid account list containing
`ok: false`; an unavailable account's address may be null. Other failed discovery
commands abort registration. Addresses and default flags are copied on initial registration;
a single account defaults automatically, and existing defaults take precedence.
Re-register to add new accounts. Existing channels and settings are preserved;
removed connector accounts are not automatically deleted from Inbox.

Existing custom names remain usable. A new canonical channel referring to an
existing custom channel stores `policy_channel = "old-name"`, inheriting its
policy; explicit rules on the canonical name override corresponding inherited
fields. Registration refuses ambiguous multiple legacy names for the same account.
Cross-channel reads query each connector/account pair once.

Registration does not install software, authenticate, or access credential files.
`inbox channel add NAME --connector CONNECTOR --account ACCOUNT` remains supported
for manual mappings. Canonical names are quoted in TOML because dots otherwise
create nested tables.

## Accounts

A connector may serve several accounts (mailboxes, linked numbers). It names
them itself; `accounts` lists the names. Every verb takes an account selector
flag whose name and position the connector announces in `capabilities`
(`--account` after the verb for gmail, `--profile` before it for whatsapp).
inbox always passes it. Credentials are entirely the connector's affair:
where they live, how they are obtained, how they are renewed. inbox never
sees a token.

## Mandatory verbs

Every verb accepts `--json`. Without it the connector prints for humans.

```text
capabilities                                  -> {connector, version, account_flag, account_position?,
                                                  verbs, optional, features, address}
accounts [--json]                             -> [{name, address, ok, default?, error?}]
threads [QUERY] [--from A] [--since T] [-n N] <acct>
                                              -> [thread-record]
search [QUERY] [--thread ID] [--from A] [--since T] [-n N] [--native] <acct>
                                              -> [message-record]
read (--message ID | --thread ID) [-n N] <acct>
                                              -> [message-record]
send WHO [--body TEXT] [--reply-to ID] [--attach FILE] <acct>
                                              -> {ok, id?, thread?, to, account} or {ok:false, reason}
resolve WHO <acct>                            -> {ok, address, name?, candidates:[{address,name}]}
                                                 or exit 2 with {ok:false, reason, candidates}
```

`--since` takes `24h`, `7d`, `30m` or an ISO date. A bare search query matches
human-visible message content: subject and body for mail, text and captions for
chat. Matching may use the service's index, so tokenization can differ. `--native`
explicitly enables advanced service syntax such as Gmail operators. `--thread`
and `--from` are common scope filters.

`--body` omitted means read stdin. `--reply-to` takes a self-contained message
ID and threads or quotes where the service can. `--attach` on a service that
cannot attach exits 2.

## Thread records

`threads` discovers independently readable message collections:

```json
{"id": "…", "account": "qmt", "name": "#finance", "type": "channel",
 "participants": ["alice"], "when": "2026-09-11T14:09:00+01:00",
 "snippet": "Latest visible message", "message_count": 42}
```

Required keys are `id`, `account`, `name`, `type`, `participants`, `when`,
`snippet`, and `message_count`. Values unavailable to a service are an empty
string/list or `null`. Types include `email`, `direct`, `group`, `channel`, and
service-specific additions. A thread ID must be accepted unchanged by
`read --thread` and `search --thread`.

`threads QUERY` helps discover the ID: it matches a display name, title,
participants, or indexed message content according to what the service can
search. Once an ID is known, `search --thread ID` has exact scope.

## Message records

The same keys from every connector, so a merged view is a sort, not a
translation:

```json
{"id": "…", "account": "qmt", "when": "2026-09-11T14:09:00+01:00",
 "from": "zhu@example.org", "from_name": "Zhu Sun", "to": ["…"],
 "subject": "…", "text": "…", "unread": true, "thread": "…",
 "attachments": [{"name": "…", "type": "…", "size": 123}]}
```

- `from` and `to` are canonical addresses (see below); `from` is `"me"` for
  the person's own messages.
- `id` is opaque but self-contained and identifies exactly one message within
  its connector account. If a native message ID is only unique inside a chat,
  the connector returns a composite ID.
- `subject` is empty on services without one. `unread` is `null` where the
  service does not track it.
- `thread` identifies the independently readable collection containing the
  message: an email chain, chat, channel, or service reply thread. It is opaque
  and accepted unchanged by `read --thread`. Chat connectors may add
  `thread_name` and `group`.
- `text` in search results may be a snippet; `read` returns the full text.

`read --thread ID` returns the complete thread in chronological order. An
explicit `-n N` may limit it to the newest N messages.

## Addresses

Each connector has one canonical address form and must accept it and echo it:
an email address; phone digits with country code; a handle. `resolve` turns
any accepted form, including a contact name, into the canonical one, or lists
candidates when the name is ambiguous. Name lookup across channels is
inbox's job, built on `resolve`.

## Optional verbs

Declared in `capabilities.optional`; inbox offers them only where declared.
Common ones: `draft` (services with a drafts folder; `{ok, draft, thread,
to, account}`), `drafts`, `draft-show`, `draft-send`, `draft-delete`,
`attachments ID [--save DIR]`, `download`, `members`, `contacts`, `recent`,
`bridge`. Anything a connector offers beyond the contract is reachable through
`inbox <connector> SUB ...`, passed through untouched.

## Features

`capabilities.features` tells inbox what the service can do:

```json
{"threads": true, "subject": true, "attach": true, "drafts": true, "groups": false, "unread": true}
```

inbox uses `subject` to tell mail-like connectors from chat-like ones when
guessing which connector a raw address belongs to.

## Exit codes

`0` ok, `1` the operation failed, `2` bad input or ambiguous recipient,
`3` refused by the connector's own guard. inbox reserves `3` for its policy.

## Rules

- A connector never acts unasked. `send` sends only when called; no verb
  marks read, deletes, or sends as a side effect.
- Own send guards are allowed as a safety net (whatsapp's config switch).
  inbox lifts them for the one call it has approved, through an environment
  variable the connector documents.
- Connector-specific flags (`--subject`, `--cc`, `--voice`) are the
  connector's; inbox passes unknown flags through after the contract ones.
