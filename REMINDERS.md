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

## 1. The reminder record

One JSON file per reminder in `~/.inbox/reminders/<id>.json`.

```json
{
  "id":      "r_f22deb",
  "text":    "Pay the KITP conference fee",
  "due":     "2026-09-11T09:00+02:00",
  "status":  "pending",
  "refs":    ["url:https://www.kitp.ucsb.edu/pay", "email:qmt:1a081b3b8909a785"],
  "source":  "manual",
  "created": "2026-09-11T00:42:24+02:00",
  "sent_at": null,
  "note":    ""
}
```

| field | meaning |
|---|---|
| `id` | `r_` plus six hex characters; the handle in every reply |
| `text` | what to be reminded of, one line |
| `due` | ISO 8601 with offset; the moment it becomes due |
| `status` | `pending` → `sent` → `done`; `snoozed` resets `due` and returns to pending |
| `refs` | kind-prefixed strings, see §3 |
| `source` | `manual`, or `ws` for a reminder derived from a store task |
| `sent_at` | when it last went out |
| `note` | free text, e.g. the person's last reply |

Created with `inbox remind add TEXT --due WHEN [--ref K:V]...`. A reminder
has no brief and no watch: it fires on `due`, once, and then waits for
`done` or `snooze`.

## 2. The watched task

Lives in the store as a ws task; the loop never creates one. The task's
`description` carries a brief, and two list fields carry the machinery.
Written by whoever creates the task, usually an agent turning a message into
work, so the sender and thread are at hand.

```yaml
name: Pay the KITP conference fee
status: open
due: 2026-09-11
priority: high
description: |
  Goal:         registration for AI at the Quantum Frontier stays valid
  State:        registered; fee unpaid; deadline Fri 11 Sep, then cancelled
  Waiting for:  payment confirmation from kitp-conf@ucsb.edu
  Next step:    pay at https://www.kitp.ucsb.edu/pay
  Agent may:    check mail for the confirmation; draft a reply to KITP; never pay
  Done when:    a confirmation mail exists
role: logistics
refs:
  - email:qmt:1a081b3b8909a785
  - url:https://www.kitp.ucsb.edu/pay
watch:
  - email:from:kitp-conf@ucsb.edu
  - email:thread:1a081b3b8909a785
```

The six brief lines are a convention, not a schema; an agent reads them as
prose. `Agent may` is the only line with teeth: the acting session (§7) is
told it and nothing beyond it. `role` names a roster role; missing means the
generic watcher. `refs` are context (§3); `watch` are signals (§4). Every ref
that names a message or thread is also a watch, so a task made from a mail
is watched without spelling it out.

## 3. Refs

Kind-prefixed text. The loop stores them, prints them into messages, and
dereferences a kind only when the matching tool is installed; unknown kinds
pass through.

```text
ws:task:<key>  ws:document:<key>  ws:person:<key>   the store, via `ws show`
email:<channel>:<message-id>                        one mail, via the channel's connector
whatsapp:<who>:<message-id>  telegram:<chat>:<msg>   one chat message
url:<https://...>                                   printed as is
file:<path>                                         read if present
```

## 4. Watches

A watch is a channel plus a query a connector already answers. The loop
runs it with `--since <last check>` and counts hits. No agent is involved.

```text
email:from:<address>          new mail from a sender          inbox search "from:X" --since T
email:thread:<message-id>     a reply in a thread             inbox read ID --thread, newer than T
email:query:<gmail query>     anything the service can search
whatsapp:chat:<who>           new messages from a chat        inbox wa read WHO --since T
telegram:chat:<who>           same, on Telegram
ws:<kind>:<key>               the object appears or changes   `ws show` succeeds / updated_at > T
file:<path>                   the file appears or changes     mtime > T
date:<YYYY-MM-DD[THH:MM]>     the moment arrives
```

`date:` is implicit for every task with a due date.

## 5. The pass

Every tick (launchd, default ten minutes; `inbox remind install --every N`):

```text
1. replies      pull the bot chat; apply every reply since the last pass (§6)
2. reminders    for each pending reminder past due: compose (§8), send, mark sent
3. tasks        for each open ws task with a watch or a due date:
                  a. run its watches since last_checked; note hits            (Python, cheap)
                  b. if no hits and not newly due: write last_checked, next task
                  c. else start ONE session of its role, read-only (§7)
                  d. act on the answer: NOTHING / MESSAGE / PROPOSE
4. exit
```

Per-task state in `~/.inbox/state/tasks/<key>.json`: `last_checked`,
`last_hits`, `last_told` (what the person was last sent, and when),
`proposal` (an open proposal awaiting a yes), `told_due` (so a due task is
announced once, not every tick).

Quiet rules: a task is spoken about at most once per hit set and once when
it becomes due; nothing at all between 23:00 and 07:00 unless due within the
hour (`[reminders] quiet = ["23:00", "07:00"]`).

## 6. Replies

The bot chat is the reply channel. A reply is matched to a reminder or task
by the message it answers (Telegram reply-to), else by an id in the text,
else it goes to the most recent open item. Only messages from the person's
own chat id count.

```text
done [id]            reminder → done; task → ws edit --status done
snooze [id] 2h|tomorrow 9|fri        push the due moment
yes | go | send      accept the open proposal on that item (§7)
no | later           drop the proposal; the task stays watched
anything else        stored in `note`; passed to the next session as context
```

## 7. Sessions

A session is one headless run of a roster role: `claude -p` with the role's
composed file as system prompt, given the task, its brief, its refs
dereferenced, the watch hits, and `last_told`. Two kinds:

**Watching** (step 3c). Tools read-only: `ws show`, `ws search`, `inbox
search`, `inbox read`. Must end with exactly one of:

```text
NOTHING                       nothing worth saying; the loop records the check
MESSAGE <text>                the loop sends the text as is
PROPOSE <text>
ACTION <one line>             e.g.  inbox email send-draft r-4838... --via personal
                              the loop sends the text and stores the action
```

**Acting** (after a `yes`). Same role, the tools its header grants, told the
stored ACTION and the `Agent may` line, nothing else. The loop passes
`--confirmed` on the send itself, because the person's yes to that exact
proposal is the per-message approval. Anything the session tries beyond the
stored action is refused by policy as usual. It ends with a one-line result
the loop sends back.

A session that fails, times out, or answers in another form counts as
NOTHING; the failure is logged.

## 8. Composing

With `[reminders] compose = true`, reminder messages (step 2) are written by
a headless, tool-less session from the reminder and its dereferenced refs,
template fallback. Tone lives in `~/.inbox/compose.md`. Task messages come
from the role session itself.

## 9. Costs

Python per tick: a handful of narrow connector queries per watched task.
Agent calls: one per task per hit set, plus one when it becomes due, plus
one per accepted proposal. A task nobody writes to and that is not due costs
nothing.

## 10. Order of work

1. Replies: done and snooze from the phone.
2. Task state files, the brief convention, `ws` gains `refs` and `watch` on
   tasks (or they ride in the description until it does).
3. Watches in Python, the NOTHING/MESSAGE/PROPOSE session, quiet hours.
4. Proposals and acting with `--confirmed`.
