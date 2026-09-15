import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from inbox import chats, cli, reminders, roles, when


class ChatRoutingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for target, value in (
            ("inbox.chats.CHATS", root / "chats.toml"),
            ("inbox.chats.AGENTS", root / "agents.toml"),
            ("inbox.chats.CURRENT", root / "state" / "current-chat.json"),
            ("inbox.paths.STATE", root / "state"),
            ("inbox.paths.REMINDERS", root / "reminders"),
        ):
            p = patch(target, value)
            p.start()
            self.addCleanup(p.stop)
        self.replies = []

    def handle(self, text):
        return chats.handle(text, self.replies.append)

    @patch("inbox.chats.roles.system_prompt", return_value="Research instructions")
    @patch("inbox.chats.roles.available", return_value={"librarian": "Ralph, research agent"})
    def test_role_discovery_selection_and_named_continuation(self, catalog, prompt):
        chats.expose_agent("librarian")
        self.handle("roles")
        self.assertIn("librarian — Ralph", self.replies[-1])
        self.assertIsNone(chats.current())
        self.handle("talk librarian")
        self.assertEqual(chats.get(chats.current()).role, "librarian")
        with patch("inbox.chats.shutil.which", return_value="claude"), \
             patch("inbox.chats.subprocess.run", return_value=subprocess.CompletedProcess(
                 [], 0, json.dumps({"result": "Found papers", "session_id": "session-1"}), ""
             )) as run, patch("inbox.chats.log.record"), patch("inbox.chats.config.reminders_via"):
            self.handle("Find papers")
            self.assertIn("--system-prompt", run.call_args.args[0])
            self.handle("save readout-papers")
            self.assertIsNone(chats.get("librarian"))
            self.assertEqual(chats.get("readout-papers").session, "session-1")
            self.handle("talk librarian")
            self.assertIsNone(chats.get(chats.current()).session)
            self.handle("talk readout-papers")
            self.handle("Summarize the first paper")
            argv = run.call_args.args[0]
            self.assertEqual(argv[argv.index("--resume") + 1], "session-1")
            self.assertNotIn("--system-prompt", argv)
        self.assertEqual(chats.current(), "readout-papers")

    @patch("inbox.chats.roles.available", side_effect=AssertionError("Must not need roster"))
    def test_existing_session_takes_precedence(self, catalog):
        chats.upsert(chats.Chat(name="email", session="existing", cwd="/tmp"))
        self.handle("talk email")
        self.assertEqual(chats.get(chats.current()).session, "existing")
        self.assertEqual(chats.get("email").cwd, "/tmp")

    @patch("inbox.chats.roles.available", return_value={"email": "Emma"})
    def test_unknown_role_does_not_create_generic_chat_or_switch(self, catalog):
        chats.upsert(chats.Chat(name="work"))
        chats.set_current("work")
        self.handle("talk typo")
        self.assertEqual(chats.current(), "work")
        self.assertIsNone(chats.get("typo"))
        self.assertIn("chats", self.replies[-1])

    @patch("inbox.chats.roles.available", return_value={"email": "Emma"})
    @patch("inbox.chats.roles.system_prompt", return_value="")
    def test_role_without_instructions_is_not_started(self, prompt, catalog):
        chats.expose_agent("email")
        self.handle("talk email")
        self.assertIsNone(chats.get("email"))
        self.assertIsNone(chats.current())
        self.assertIn("Could not load instructions", self.replies[-1])

    def test_save_refuses_collision_and_invalid_name(self):
        chats.upsert(chats.Chat(name="a", session="one"))
        chats.upsert(chats.Chat(name="b", session="two"))
        chats.set_current("a")
        for name in ("b", "../escape", ""):
            self.handle("save " + name)
            self.assertEqual(chats.current(), "a")
            self.assertEqual(chats.get("a").session, "one")
            self.assertEqual(chats.get("b").session, "two")

    def test_saved_reminder_stays_linked_on_announcement_and_done(self):
        r = reminders.add("Pay fee", when.parse("in 1h"), [], role="logistics")
        reminders.ensure_chat(r)
        chats.select(r.id)
        self.handle("save conference")
        reminders.ensure_chat(r)
        self.assertEqual(list(chats.all_chats()), ["conference"])
        self.assertIn("talk conference", reminders.announcement(r, [], "due"))
        with patch("inbox.chats.turn", return_value=(True, "Checked")), patch("inbox.reminders.tell"):
            reminders.converse(r, "Check it")
        self.assertEqual(chats.current(), "conference")
        self.handle("done")
        self.assertEqual(reminders.get(r.id).status, "done")
        self.assertIsNone(chats.get("conference"))

    @patch("inbox.chats.roles.available", side_effect=roles.RoleError("Roster unavailable"))
    def test_listing_works_without_roster_and_exposure_reports_failure(self, catalog):
        self.handle("chats")
        self.assertIn("Agents —", self.replies[-1])
        self.assertIn("Conversations —", self.replies[-1])
        with self.assertRaisesRegex(ValueError, "Roster unavailable"):
            chats.expose_agent("email")
        self.handle("talk email")
        self.assertIn("No exposed agent", self.replies[-1])
        self.assertEqual(chats.all_chats(), {})

    def test_chat_listing_uses_names_without_session_ids(self):
        chats.upsert(chats.Chat(name="design", session="secret-session-id"))
        self.handle("chats")
        self.assertIn("design", self.replies[-1])
        self.assertNotIn("secret-session-id", self.replies[-1])

    def test_names_with_spaces_round_trip_and_route_to_codex(self):
        chats.upsert(chats.Chat(name="Inbox Chat", session="thread-1", backend="codex", cwd="/tmp"))
        self.handle("talk Inbox Chat")
        self.assertEqual(chats.current(), "Inbox Chat")
        with patch("inbox.codex.turn", return_value=(True, "Context retained")) as turn, \
             patch("inbox.chats.log.record"), patch("inbox.chats.config.reminders_via"):
            self.handle("Do you remember our earlier discussion?")
        turn.assert_called_once_with("thread-1", "Do you remember our earlier discussion?", cwd="/tmp", dry_run=False)
        self.assertEqual(self.replies[-1], "[Inbox Chat] Context retained")
        self.handle("save Inbox Conversation")
        self.assertEqual(chats.get("Inbox Conversation").backend, "codex")
        self.assertEqual(chats.get("Inbox Conversation").session, "thread-1")

    def test_done_sentence_is_a_prompt_not_a_close_command(self):
        chats.upsert(chats.Chat(name="Inbox Chat"))
        chats.set_current("Inbox Chat")
        with patch("inbox.chats.turn", return_value=(True, "Okay")) as turn:
            self.handle("Done with the design, what is next?")
        turn.assert_called_once()
        self.assertIsNotNone(chats.get("Inbox Chat"))

    def test_old_chat_files_default_to_claude(self):
        chats.CHATS.write_text('[chats.design]\nsession = "claude-session"\n')
        self.assertEqual(chats.get("design").backend, "claude")

    @patch.dict("os.environ", {"CODEX_THREAD_ID": "current-codex-thread"})
    def test_expose_detects_current_codex_session_and_preserves_selection(self):
        with patch("builtins.print"):
            cli.main(["chat", "expose", "Inbox Chat"])
        c = chats.get("Inbox Chat")
        self.assertEqual(c.backend, "codex")
        self.assertEqual(c.session, "current-codex-thread")
        self.assertEqual(c.cwd, str(Path.cwd()))
        self.assertIsNone(chats.current())
        with self.assertRaises(SystemExit):
            cli.main(["chat", "expose", "Inbox Chat", "--backend", "codex", "--session", "another-thread"])
        self.assertEqual(chats.get("Inbox Chat").session, "current-codex-thread")

    @patch.dict("os.environ", {"CODEX_THREAD_ID": "current-codex-thread"})
    def test_explicit_session_keeps_claude_default(self):
        with patch("builtins.print"):
            cli.main(["chat", "expose", "Claude Chat", "--session", "claude-session"])
        self.assertEqual(chats.get("Claude Chat").backend, "claude")

    @patch("inbox.chats.roles.available", return_value={"email": "Mail", "coding": "Code"})
    @patch("inbox.chats.roles.system_prompt", return_value="Mail instructions")
    def test_agent_always_starts_fresh_and_only_saved_sessions_appear(self, prompt, catalog):
        with patch("builtins.print"):
            cli.main(["agent", "expose", "email", "--name", "Emma", "--about", "Email help"])
        self.handle("talk emma")
        first = chats.get(chats.current())
        first.session = "first-session"
        chats.upsert(first)
        self.handle("talk Emma")
        second = chats.get(chats.current())
        self.assertNotEqual(first.name, second.name)
        self.assertIsNone(second.session)
        self.assertEqual(chats.get(first.name).session, "first-session")
        self.handle("chats")
        menu = self.replies[-1]
        self.assertIn("Emma (email) — Email help", menu)
        self.assertNotIn("coding", menu)
        self.assertNotIn("• " + first.name, menu)
        self.assertNotIn("• " + second.name, menu)
        self.handle("save Inbox cleanup")
        self.handle("chats")
        self.assertIn("• Inbox cleanup", self.replies[-1])
        self.handle("talk coding")
        self.assertEqual(chats.current(), "Inbox cleanup")
        self.assertIn("No exposed agent", self.replies[-1])
        self.handle("talk " + first.name)
        self.assertEqual(chats.current(), "Inbox cleanup")

    @patch("inbox.chats.roles.available", return_value={"email": "Mail", "logistics": "Messages"})
    def test_agent_and_conversation_names_cannot_collide(self, catalog):
        chats.expose_agent("email", "Emma")
        chats.upsert(chats.Chat(name="work", session="keep"))
        chats.set_current("work")
        self.handle("save emma")
        self.assertEqual(chats.current(), "work")
        self.handle("new Emma")
        self.assertEqual(chats.current(), "work")
        with self.assertRaises(ValueError):
            chats.expose_agent("email", "WORK")
        with self.assertRaises(ValueError):
            chats.expose_agent("logistics", "email")
        for command in ("add", "expose"):
            for reserved in ("Emma", "email"):
                with self.assertRaises(SystemExit):
                    cli.main(["chat", command, reserved, "--session", "other"])
        self.assertEqual(chats.get("work").session, "keep")

    @patch("inbox.chats.roles.available", return_value={"email": "Mail"})
    def test_reexposing_role_with_new_name_renames_one_entry(self, catalog):
        chats.expose_agent("email", "Emma")
        chats.expose_agent("EMAIL", "Mail helper")
        self.assertEqual(list(chats.exposed_agents()), ["Mail helper"])
        self.assertEqual(chats.exposed_agents()["Mail helper"]["role"], "email")

    @patch("inbox.chats.roles.available", return_value={"email": "Mail"})
    def test_hide_and_reexpose_preserve_conversations(self, catalog):
        chats.expose_agent("email")
        chats.upsert(chats.Chat(name="Letters", session="saved", role="email"))
        chats.set_current("Letters")
        with patch("builtins.print"):
            cli.main(["agent", "hide", "email"])
            cli.main(["chat", "hide", "Letters"])
        self.assertNotIn("• Letters", chats.listing())
        self.assertEqual(chats.get("Letters").session, "saved")
        self.handle("talk email")
        self.assertIn("No exposed agent", self.replies[-1])
        with patch("builtins.print"), patch.dict("os.environ", {}, clear=True):
            cli.main(["chat", "expose", "Letters"])
        self.handle("talk letters")
        self.assertEqual(chats.current(), "Letters")
        self.assertEqual(chats.get("Letters").session, "saved")

    @patch("inbox.chats.roles.available", return_value={"email": "Mail"})
    @patch("inbox.chats.roles.system_prompt", return_value="Mail instructions")
    def test_remote_agent_uses_name_and_role_alias_and_hides_by_either(self, prompt, catalog):
        with patch("builtins.print") as output:
            cli.main(["remote", "expose", "agent", "EMAIL", "--name", "Emma", "--about", "Email help"])
        self.assertIn("talk Emma", output.call_args.args[0])
        self.assertIn("talk email", output.call_args.args[0])
        self.handle("talk Emma")
        first = chats.current()
        self.handle("talk email")
        self.assertNotEqual(first, chats.current())
        self.assertEqual(chats.get(chats.current()).role, "email")
        with patch("builtins.print") as output:
            cli.main(["remote", "hide", "agent", "EMAIL"])
        self.assertEqual(output.call_args.args[0], "hidden")
        self.handle("talk Emma")
        self.assertIn("No exposed agent", self.replies[-1])

    @patch.dict("os.environ", {"CODEX_THREAD_ID": "remote-thread"}, clear=True)
    def test_remote_exposes_and_hides_current_conversation(self):
        with patch("builtins.print"):
            cli.main(["remote", "expose", "conversation", "Remote Design", "--cwd", "/tmp", "--about", "Design work"])
        chat = chats.get("Remote Design")
        self.assertEqual((chat.backend, chat.session, chat.cwd),
                         ("codex", "remote-thread", str(Path("/tmp").resolve())))
        with patch("builtins.print"):
            cli.main(["remote", "list"])
            cli.main(["remote", "hide", "conversation", "Remote Design"])
        self.assertFalse(chats.get("Remote Design").exposed)
        self.assertEqual(chats.get("Remote Design").session, "remote-thread")

    def test_exposing_current_session_does_not_silently_keep_another_session(self):
        chats.upsert(chats.Chat(name="Project notes", session="old-session", backend="codex", exposed=False))
        with patch.dict("os.environ", {"CODEX_THREAD_ID": "new-session"}, clear=True), \
             self.assertRaisesRegex(SystemExit, "already refers to another conversation"):
            cli.main(["remote", "expose", "conversation", "Project notes"])
        self.assertEqual(chats.get("Project notes").session, "old-session")
        self.assertFalse(chats.get("Project notes").exposed)

    def test_menu_aliases_and_plain_sentences(self):
        for command in ("chats", "available", "available chats", "agents", "roles", "who", "talk"):
            self.handle(command)
            self.assertIn("Agents — start a new conversation", self.replies[-1])
            self.assertIn("Conversations — resume", self.replies[-1])
        chats.upsert(chats.Chat(name="work"))
        chats.set_current("work")
        with patch("inbox.chats.turn", return_value=(True, "Okay")) as turn:
            self.handle("Available chats would be useful")
        turn.assert_called_once()

    @patch("inbox.chats.roles.available", return_value={"email": "Mail"})
    def test_reminder_does_not_replace_agent_or_unrelated_session(self, catalog):
        chats.expose_agent("email", "Pay fee")
        chats.upsert(chats.Chat(name="pay-fee", session="unrelated"))
        r = reminders.add("Pay fee", when.parse("in 1h"), [], role="email")
        reminders.ensure_chat(r)
        c = next(c for c in chats.all_chats().values() if c.reminder == r.id)
        self.assertNotEqual(c.name, "pay-fee")
        self.assertEqual(chats.get("pay-fee").session, "unrelated")
        self.assertIn("talk " + c.name, reminders.announcement(r, [], "due"))
        chats.hide_conversation(c.name)
        reminders.ensure_chat(r)
        self.assertTrue(chats.get(c.name).exposed)


class RoleCatalogTests(unittest.TestCase):
    def setUp(self):
        roles.system_prompt.cache_clear()
        self.addCleanup(roles.system_prompt.cache_clear)

    @patch("inbox.roles.shutil.which", return_value="roster")
    @patch("inbox.roles.subprocess.run")
    def test_uninstalled_role_uses_source_definition_and_skill_instructions(self, run, which):
        source = "---\nskills: [inbox]\n---\nEmma instructions"
        run.side_effect = [subprocess.CompletedProcess([], 1, ""), subprocess.CompletedProcess([], 0, source)]
        prompt = roles.system_prompt("email")
        self.assertIn(source, prompt)
        self.assertIn("roster show-skill NAME", prompt)
        self.assertEqual(run.call_args.args[0], ["roster", "show", "email"])

    @patch("inbox.roles.shutil.which", return_value="roster")
    @patch("inbox.roles.subprocess.run")
    def test_installed_prompt_keeps_embedded_instructions(self, run, which):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "role.md"
            f.write_text("---\nname: email\n---\nEmbedded skills and role")
            run.return_value = subprocess.CompletedProcess([], 0, str(f))
            self.assertEqual(roles.system_prompt("email"), "Embedded skills and role")
            self.assertEqual(run.call_count, 1)

    @patch("inbox.roles.shutil.which", return_value="roster")
    @patch("inbox.roles.subprocess.run")
    def test_reads_roster_json(self, run, which):
        run.return_value = subprocess.CompletedProcess([], 0, '{"roles":[{"name":"email","description":"Emma"}]}')
        self.assertEqual(roles.available(), {"email": "Emma"})
        self.assertEqual(run.call_args.args[0], ["roster", "list", "roles", "--json"])

    @patch("inbox.roles.shutil.which", return_value="roster")
    @patch("inbox.roles.subprocess.run")
    def test_invalid_catalog_and_timeouts_are_reported(self, run, which):
        for output in ("not JSON", "{}", '{"roles":null}'):
            run.return_value = subprocess.CompletedProcess([], 0, output)
            with self.assertRaises(roles.RoleError):
                roles.available()
        run.side_effect = subprocess.TimeoutExpired("roster", 10)
        with self.assertRaises(roles.RoleError):
            roles.available()


if __name__ == "__main__":
    unittest.main()
