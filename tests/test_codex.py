import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from inbox import codex


class CodexTurnTests(unittest.TestCase):
    @patch("inbox.codex.command", return_value="/app/codex")
    @patch("inbox.codex.subprocess.run")
    def test_resumes_exact_session_and_returns_final_response_only(self, run, command):
        def execute(argv, **kwargs):
            Path(argv[argv.index("--output-last-message") + 1]).write_text("Final answer\n")
            return subprocess.CompletedProcess(argv, 0, "progress and other output", "")
        run.side_effect = execute
        result = codex.turn("thread-id", "--do-not-treat-as-flag\nHello", cwd="/project")
        self.assertEqual(result, (True, "Final answer"))
        argv = run.call_args.args[0]
        self.assertEqual(argv[:4], ["/app/codex", "exec", "resume", "thread-id"])
        self.assertEqual(argv[-1], "-")
        self.assertEqual(run.call_args.kwargs["cwd"], "/project")
        self.assertIn("--do-not-treat-as-flag\nHello", run.call_args.kwargs["input"])
        self.assertFalse(any("bypass" in a for a in argv))

    @patch("inbox.codex.command", return_value="/app/codex")
    @patch("inbox.codex.subprocess.run")
    def test_process_failure_is_not_reported_as_success(self, run, command):
        run.return_value = subprocess.CompletedProcess([], 1, "", "Session not found")
        self.assertEqual(codex.turn("missing", "Hello"), (False, "Session not found"))

    @patch("inbox.codex.command", return_value="/app/codex")
    @patch("inbox.codex.subprocess.run")
    def test_missing_answer_and_timeout(self, run, command):
        run.return_value = subprocess.CompletedProcess([], 0, "", "")
        self.assertEqual(codex.turn("thread", "Hello"), (False, "Codex returned no final response"))
        run.side_effect = subprocess.TimeoutExpired("codex", 900)
        self.assertFalse(codex.turn("thread", "Hello")[0])

    @patch("inbox.codex.command", return_value="/app/codex")
    @patch("inbox.codex.subprocess.run")
    def test_dry_run_and_missing_session_do_not_start_process(self, run, command):
        self.assertTrue(codex.turn("thread", "Hello", dry_run=True)[0])
        self.assertFalse(codex.turn(None, "Hello")[0])
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
