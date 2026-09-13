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

`inbox remind run`, every ten minutes from launchd. No agent unless the
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

A reply names a reminder by its id anywhere in the text; without one it goes
to the most recently told reminder.

| reply | effect |
|---|---|
| `done [id]` | closes it; a `ws:task:` ref is marked done |
| `snooze [id] 2h` / `tomorrow 9am` | new due time, will be told again |
| `fresh [id] [text]` | forget the session; start over (then `text` is the prompt) |
| `resume [id] [text]` | continue the recorded session (the default when one exists) |
| anything else | the prompt for one turn of the reminder's role |

## 5. A turn

The person's text is the prompt. The loop starts Claude headless: resumed
with `--resume <session>` when the reminder has one and the mode is not
fresh, else fresh with the role's installed subagent file as the system
prompt (`roster path ROLE`) plus the reminder file verbatim and the rule that
the answer goes to a phone. New watch hits since the last check are appended
to the prompt. The role runs with its full tools; sending still needs the
person's yes in the conversation, which the role gives as `--confirmed`.

The session's final answer is sent back verbatim, with "reply to continue,
or done". Its session id is recorded in the reminder, so the next reply
continues it. `inbox remind say ID TEXT` is the same turn from a terminal.

## 6. Costs

A quiet reminder costs nothing per pass: the watches are connector queries.
An agent runs only when the person replies. Each turn is one headless call,
ten seconds to a minute, logged with its cost in `inbox log`.
