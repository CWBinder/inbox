import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from inbox import cli, config, connectors, paths, policy, registration


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = self.root / 'config.toml'
        self.config.write_text('# Keep this comment\n[me]\nname = "Test"\n')
        self.policy = self.root / 'policy.toml'
        self.policy.write_text('[defaults]\nsend = "confirm"\n')
        for key, value in [('CONFIG', self.config), ('POLICY', self.policy)]:
            patcher = patch.object(paths, key, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.clear()
        self.addCleanup(self.clear)
        self.caps = {'connector': 'slack', 'version': '1', 'account_flag': '--account',
                     'verbs': ['accounts', 'search', 'read', 'send', 'resolve']}
        self.accounts = [{'name': 'qmt', 'address': 'user@example.org', 'ok': True, 'default': True},
                         {'name': 'personal', 'address': 'personal@example.org', 'ok': True}]
        self.executable = self.root / 'my-slack-cli'
        self.make_connector()

    def clear(self):
        config.load.cache_clear()
        config.channels.cache_clear()
        policy.load.cache_clear()
        connectors.capabilities.cache_clear()

    def make_connector(self, broken=None):
        payload = {'capabilities': self.caps, 'accounts': self.accounts}
        self.executable.write_text(f'''#!{sys.executable}
import json, sys
payload = json.loads({json.dumps(payload)!r})
args = sys.argv[1:]
if args[0] == 'capabilities':
    print(json.dumps(payload['capabilities']))
elif args[0] == 'accounts':
    print({broken!r} if {broken is not None!r} else json.dumps(payload['accounts']))
elif args[0] == 'search':
    account = args[args.index('--account') + 1]
    print(json.dumps([{{'id': 'message-1', 'account': account, 'text': 'Found', 'when': '2026-09-16'}}]))
else:
    print(json.dumps({{'args': args}}))
''')
        self.executable.chmod(0o755)

    def run_cli(self, *args):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            cli.main(args)
        return output.getvalue()

    def test_cli_discovers_accounts_and_runs_correct_executable(self):
        output = self.run_cli('connector', 'add', str(self.executable))
        self.assertIn('slack.qmt: ok', output)
        self.assertIn('slack.personal: ok', output)
        self.assertIn('# Keep this comment', self.config.read_text())
        data = tomllib.loads(self.config.read_text())
        self.assertEqual(data['connectors']['slack']['command'], str(self.executable))
        self.assertEqual(set(data['channels']), {'slack.qmt', 'slack.personal'})
        self.assertEqual(config.channel('slack.qmt').address, 'user@example.org')
        self.assertEqual(config.default_channel('slack').account, 'qmt')
        for account in ('qmt', 'personal'):
            ok, response, _, _ = connectors.run(config.channel('slack.' + account), 'read', 'message-1')
            self.assertTrue(ok)
            self.assertEqual(response['args'], ['read', 'message-1', '--account', account, '--json'])
        passthrough = cli.build_parser().parse_args(['slack', '--via', 'slack.personal', 'contacts'])
        self.assertEqual(passthrough.via, 'slack.personal')

    def test_register_by_path_lookup_and_account_flag_before_verb(self):
        self.caps.update(account_flag='--profile', account_position='before')
        self.make_connector()
        with patch.dict(os.environ, {'PATH': str(self.root) + os.pathsep + os.environ['PATH']}):
            self.run_cli('connector', 'add', 'my-slack-cli')
        ok, result, _, _ = connectors.run(config.channel('slack.qmt'), 'read', 'm')
        self.assertTrue(ok)
        self.assertEqual(result['args'], ['--profile', 'qmt', 'read', 'm', '--json'])

    def test_fresh_install_registration_and_search_in_separate_processes(self):
        home = self.root / 'fresh-inbox'
        env = {**os.environ, 'INBOX_HOME': str(home)}
        def run(*args):
            result = subprocess.run([sys.executable, '-m', 'inbox.cli', *args],
                                    env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout
        run('init')
        data = tomllib.loads((home / 'config.toml').read_text())
        self.assertFalse(data.get('channels'))
        run('connector', 'add', str(self.executable))
        results = json.loads(run('search', 'update', '--via', 'slack.personal', '--json'))
        self.assertEqual(results[0]['account'], 'personal')
        self.assertEqual(results[0]['channel'], 'slack.personal')

    def test_existing_connector_alias_without_command_gets_explicit_mapping(self):
        self.config.write_text('[connectors.slack]\nalias = "sl"\n')
        self.executable.rename(self.root / 'slack')
        with patch.dict(os.environ, {'PATH': str(self.root) + os.pathsep + os.environ['PATH']}):
            self.run_cli('connector', 'add', 'slack')
        spec = config.load()['connectors']['slack']
        self.assertEqual(spec['alias'], 'sl')
        self.assertEqual(spec['command'], str(self.root / 'slack'))

    def test_repeat_registration_is_noop_and_discovers_new_accounts(self):
        self.run_cli('connector', 'add', str(self.executable))
        first = self.config.read_bytes()
        self.run_cli('connector', 'add', str(self.executable))
        self.assertEqual(first, self.config.read_bytes())
        self.accounts.append({'name': 'new', 'ok': False})
        self.make_connector()
        output = self.run_cli('connector', 'add', str(self.executable))
        self.assertIn('slack.new: unavailable', output)
        self.assertEqual(len(config.channels()), 3)

    def test_existing_alias_preserves_policy_and_does_not_duplicate_reads(self):
        self.config.write_text(f'''# Keep this comment
[connectors.slack]
command = {json.dumps(str(self.executable))}
alias = "sl"
[channels.work]
connector = "slack"
account = "qmt"
default = true
[reminders]
via = "work"
''')
        self.policy.write_text('[channels.work]\nsend = "draft-only"\ndestructive = "deny"\n')
        self.run_cli('connector', 'add', str(self.executable))
        self.assertFalse(policy.send(config.channel('slack.qmt'), 'alice', True).allowed)
        self.assertFalse(policy.destructive(config.channel('slack.qmt'), True, 'delete').allowed)
        self.assertTrue(policy.send(config.channel('slack.personal'), 'alice', True).allowed)
        self.assertEqual(config.load()['reminders']['via'], 'work')
        self.assertEqual(config.load()['connectors']['slack']['alias'], 'sl')
        self.assertEqual(len(cli._channels_for(None)), 2)
        self.assertEqual(len(cli._channels_for('work,slack.qmt')), 1)
        self.assertEqual(config.default_channel('slack').name, 'work')

        self.policy.write_text('[channels.work]\nsend = "allow"\nallow_to = ["alice"]\n')
        policy.load.cache_clear()
        with patch.object(connectors, 'resolve', return_value=None):
            self.assertTrue(policy.send(config.channel('slack.qmt'), 'alice', False).allowed)
            self.assertFalse(policy.send(config.channel('slack.qmt'), 'bob', True).allowed)

    def test_invalid_discovery_never_changes_configuration(self):
        variants = [({}, self.accounts), ({**self.caps, 'connector': 'bad.name'}, self.accounts),
                    ({**self.caps, 'verbs': ['accounts']}, self.accounts),
                    ({**self.caps, 'account_flag': 'qmt'}, self.accounts),
                    (self.caps, []), (self.caps, [{'name': 'qmt'}]),
                    (self.caps, [{'name': 'qmt.bad', 'ok': True}]),
                    (self.caps, [self.accounts[0], self.accounts[0]])]
        original = self.config.read_bytes()
        for caps, accounts in variants:
            with self.subTest(caps=caps, accounts=accounts):
                with patch.object(registration, '_query', side_effect=[caps, accounts]):
                    with self.assertRaises(registration.RegistrationError):
                        self.run_cli('connector', 'add', str(self.executable))
                self.assertEqual(self.config.read_bytes(), original)

    def test_malformed_output_and_missing_executable(self):
        self.make_connector(broken='not JSON')
        for executable in (str(self.executable), str(self.root / 'missing')):
            with self.assertRaises(registration.RegistrationError):
                self.run_cli('connector', 'add', executable)
        self.assertNotIn('channels', tomllib.loads(self.config.read_text()))

    def test_existing_clients_may_report_unavailable_accounts_with_exit_one(self):
        accounts = [{'name': 'qmt', 'ok': False, 'address': None, 'error': 'login required'}]
        responses = [subprocess.CompletedProcess([], 0, json.dumps(self.caps), ''),
                     subprocess.CompletedProcess([], 1, json.dumps(accounts), '')]
        with patch.object(registration.subprocess, 'run', side_effect=responses):
            output = self.run_cli('connector', 'add', str(self.executable))
        self.assertIn('slack.qmt: unavailable', output)
        self.assertIsNone(config.channel('slack.qmt').address)

    def test_conflicts_leave_config_unchanged(self):
        for extra in ('[connectors.slack]\ncommand = "some-other-cli"\n',
                      '[channels."slack.qmt"]\nconnector = "gmail"\naccount = "qmt"\n'):
            with self.subTest(extra=extra):
                self.config.write_text(extra)
                self.clear()
                with self.assertRaises(registration.RegistrationError):
                    self.run_cli('connector', 'add', str(self.executable))
                self.assertEqual(self.config.read_text(), extra)

    def test_reserved_connector_name_rejected(self):
        self.caps['connector'] = 'send'
        self.make_connector()
        with self.assertRaisesRegex(registration.RegistrationError, 'conflicts'):
            self.run_cli('connector', 'add', str(self.executable))

    def test_legacy_add_handles_quoted_canonical_names(self):
        self.run_cli('channel', 'add', 'slack.qmt', '--connector', 'slack', '--account', 'qmt')
        self.assertEqual(config.channel('slack.qmt').account, 'qmt')
        with self.assertRaises(SystemExit):
            self.run_cli('channel', 'add', 'slack.qmt', '--connector', 'slack', '--account', 'qmt')
        self.run_cli('channel', 'add', 'slack.qmt', '--connector', 'slack', '--account', 'qmt', '--force', '--address', 'alice')
        self.assertEqual(config.channel('slack.qmt').address, 'alice')

    def test_process_failure_and_timeout_do_not_write(self):
        original = self.config.read_bytes()
        with patch.object(registration.subprocess, 'run', side_effect=subprocess.TimeoutExpired('test', 30)):
            with self.assertRaises(registration.RegistrationError):
                self.run_cli('connector', 'add', str(self.executable))
        with patch.object(registration.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'failed')):
            with self.assertRaises(registration.RegistrationError):
                self.run_cli('connector', 'add', str(self.executable))
        self.assertEqual(self.config.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
