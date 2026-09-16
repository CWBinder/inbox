# Reminders and watched tasks

Two objects, one loop.

A **reminder** is a poke at a time: text, a due moment, refs. It fires once.

A **watched task** is a piece of work the person wants seen through: it has
a brief that says what is going on, a watch list that says which signals
matter, and a role that is asked to judge them. It is chased until done.

The **loop** is `inbox remind run`, a plain Python pass started by a timer.
It reads replies, checks watches, and starts short agent sessions only when
something has changed or something is due. Nothing stays running between
passes. The loop owns every side effect: it sends, it logs, it applies
policy. An agent only ever returns text.

## 1. The reminder file

One Markdown file per reminder in `~/.inbox/reminders/<id>.md`. The YAML
header is what the loop reads; the body is the brief, written for whoever
picks the reminder up later, human or agent.

```markdown
---
id: pay-the-kitp-conference-fee
due: 2026-09-11 09:00
status: told                # pending | told | snoozed | done
role: logistics             # a roster role; omitted means a plain watcher
session: 0de91320-...       # the claude session the conversation continues in
mode: resume                # resume | fresh: the person's choice, once
refs:
  - email:qmt:1a081b3b8909a785
  - url:https://www.kitp.ucsb.edu/pay
watch:
  - email:from:kitp-conf@ucsb.edu
created: 2026-09-11 00:42
told_at: 2026-09-12 20:54
checked_at: 2026-09-13 21:20
---

# Pay the KITP conference fee

**Goal.** Keep the registration.
**State.** Registered, unpaid; KITP cancels after Friday.
**Waiting for.** A payment confirmation from kitp-conf@ucsb.edu.
**Next step.** Pay at the link.
**Agent may.** Check mail and report; draft a reply if asked. Never pay, never cancel.
**Done when.** A confirmation mail exists, or Christian says done.

## Log
- 2026-09-11 00:42  created
- 2026-09-12 20:54  told (due)
```

A plain poke is the same file with only a title. `inbox remind add` writes
that; `inbox remind new` writes the six-heading template and opens it in
`$EDITOR`. Ids are slugs of the title, because they get typed in replies.
The log at the bottom is appended by the loop.

## 2. Refs and watches

Refs are kind-prefixed pointers to what the reminder is about: `ws:task:x`,
`email:<channel>:<id>`, `whatsapp:<who>:<id>`, `url:`, `file:`. Watches are
what the loop checks for changes, without an agent:

| watch | the loop runs |
|---|---|
| `email:from:<addr>` | `gmail search from:<addr> --since <last check>` on every mail channel |
| `email:thread:<channel>:<id>` | mail in that thread since the last check |
| `whatsapp:chat:<who>` | `whatsapp search --chat <who> --since <last check>` |
| `ws:<ref>` | `ws show`; a hit when `updated_at` is newer than the last check |

Every message ref implies a watch on its thread; a `ws:` ref implies a watch
on that object. Explicit watches cover what refs cannot say, such as any mail
from a sender. `inbox remind show ID` lists both; `inbox remind check ID`
runs them now.

## 3. The pass

`inbox remind run`, at the configured launchd interval (currently every minute on Christian’s Mac). No agent unless the
person asks for one.

1. Read the person's replies on the reminder channel since the last pass.
   Apply each (section 4).
2. Any open ws task with a due date and no reminder of its own becomes one.
3. For each open reminder: due and not yet told, or watches hit? Then tell
   the person: the title, why, the new items, the first line of the brief,
   and how to reply. Mark it told. Otherwise record the check time.

A told reminder is not repeated. It comes up again only on a new watch hit,
after a snooze, or when the person replies.

## 4. Replies

Messages on the reminder channel follow the chat protocol (README, "Chats").
A reminder with a role gets an exposed conversation when announced. `chats`
shows two blocks: exposed agents (start fresh) and exposed conversations
(resume). `talk NAME` selects either; every selection of an agent starts a new
conversation, while the reminder’s conversation retains its recorded session.
The notification tells you which name to select. It does not change your
current conversation automatically.

`save NAME` names and exposes the current conversation while preserving its
session and reminder link. `leave` or `leave NAME` stops routing new messages
there while keeping the conversation exposed. `remove NAME` removes its Inbox
mapping but does not complete the reminder; `snooze ID 2h` postpones it. A
reminder can still be completed from the Mac with `inbox remind done ID`. With
no current conversation, the bot shows the menu. Exposing a reminder does not
expose its role as a generic agent; use `inbox remote expose agent ROLE` for
that. A future reminder notification re-exposes its conversation if removed or
hidden.

## 5. A turn

The prompt is the person's text. The loop runs Claude headless with the tool
CLIs allowed (`inbox`, `ws`, `pplx`, the connectors, Read/Glob/Grep):
`--resume <session>` when the chat has one, else `--system-prompt` built from
the role's installed subagent file (`roster path ROLE`) plus the reminder
file verbatim and the rule that the answer goes to a phone. The final answer
is sent back verbatim under `[id]`; the session id is recorded on the chat
and the reminder, so the next message continues it. `inbox remind say ID
TEXT` is the same turn from a terminal.

## 6. Costs

A quiet reminder costs nothing per pass: the watches are connector queries.
An agent runs only when the person writes. Each turn is one headless call,
ten seconds to a minute, logged with its cost in `inbox log`.
