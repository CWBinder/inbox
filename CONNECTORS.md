# The connector contract

A connector is a command on PATH that talks to one messaging service and
speaks the verbs below. inbox never imports it: it builds a command line from
a channel's connector and account, runs it, and parses the JSON. Any language
qualifies. Conformance is membership; there is no registration.

Two existing connectors are the reference: the [whatsapp](../whatsapp) and
[gmail](../gmail) clients. `inbox connectors --check NAME` runs this contract
against an installed connector and reports what is missing.

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
search [QUERY] [--since T] [-n N] <acct>      -> [record]      QUERY in the service's own syntax
read ID [--thread] <acct>                     -> [record]      the message, or its whole thread
send WHO [--body TEXT] [--reply-to ID] [--attach FILE] <acct>
                                              -> {ok, id?, thread?, to, account} or {ok:false, reason}
resolve WHO <acct>                            -> {ok, address, name?, candidates:[{address,name}]}
                                                 or exit 2 with {ok:false, reason, candidates}
```

`--since` takes `24h`, `7d`, `30m` or an ISO date. `--body` omitted means
read stdin. `--reply-to` threads or quotes where the service can, and is
ignored where it cannot. `--attach` on a service that cannot attach exits 2.

## The message record

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
- `subject` is empty on services without one. `unread` is `null` where the
  service does not track it.
- `thread` is a thread id for mail and the chat id for chat. Chat connectors
  add `thread_name` and `group`.
- `text` in search results may be a snippet; `read` returns the full text.

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
