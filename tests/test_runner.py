from __future__ import annotations

import fcntl
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class RunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix='mirror-runner-')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.project = self.directory / 'project with spaces'
        scripts = self.project / 'scripts'
        scripts.mkdir(parents=True)
        self.lock = self.directory / 'mirror.lock'
        self.runner = scripts / 'run-mirror.sh'
        source = (
            Path(__file__).resolve().parents[1] / 'scripts' / 'run-mirror.sh'
        ).read_text()
        # Exercise many rotations without generating tens of MiB in each test.
        self.runner.write_text(
            source.replace('$((10 * 1024 * 1024))', '64').replace(
                '/tmp/gitea-mirror.lock', str(self.lock)
            )
        )
        self.runner.chmod(0o755)
        source_scripts = Path(__file__).resolve().parents[1] / 'scripts'
        for name in ('run-owned.sh', 'run-stars.sh', 'run-org.sh'):
            wrapper = scripts / name
            wrapper.write_text((source_scripts / name).read_text())
            wrapper.chmod(0o755)
        self.output = self.directory / 'output'
        self.output.write_bytes(b'')
        self.invocations = self.directory / 'invocations'
        binaries = self.directory / 'bin'
        binaries.mkdir()
        docker = binaries / 'docker'
        docker.write_text(
            '#!/bin/sh\n'
            'printf "%s\\n" "$@" >> "$MIRROR_TEST_INVOCATIONS"\n'
            'cat "$MIRROR_TEST_OUTPUT"\n'
            'exit "${MIRROR_TEST_EXIT_CODE:-0}"\n'
        )
        docker.chmod(0o755)
        self.environment = {
            **os.environ,
            'PATH': f'{binaries}:{os.defpath}',
            'MIRROR_TEST_OUTPUT': str(self.output),
            'MIRROR_TEST_INVOCATIONS': str(self.invocations),
        }

    def run_job(
        self,
        payload: bytes,
        exit_code: int = 0,
        *,
        script: str = 'run-mirror.sh',
        args: tuple[str, ...] = (),
    ) -> subprocess.CompletedProcess:
        self.output.write_bytes(payload)
        return subprocess.run(
            [str(self.runner.parent / script), *args],
            cwd=self.directory,
            env={**self.environment, 'MIRROR_TEST_EXIT_CODE': str(exit_code)},
            capture_output=True,
            timeout=10,
        )

    def retained_output(self) -> bytes:
        output = b''
        for name in ('mirror.log.3', 'mirror.log.2', 'mirror.log.1', 'mirror.log'):
            path = self.project / name
            if path.exists():
                self.assertLessEqual(path.stat().st_size, 64)
                output += path.read_bytes()
        self.assertLessEqual(len(list(self.project.glob('mirror.log*'))), 4)
        return output

    def test_rotation_keeps_recent_unicode_lines_across_runs(self) -> None:
        first = ''.join(f'{i}: mirrored 🍌\n' for i in range(30)).encode()
        second = ''.join(f'{i}: failed 🍎\n' for i in range(30, 60)).encode()
        self.assertEqual(self.run_job(first).returncode, 0)
        self.assertEqual(self.run_job(second).returncode, 0)
        retained = self.retained_output()
        self.assertTrue((first + second).endswith(retained))
        self.assertIn('59: failed 🍎\n'.encode(), retained)
        for path in self.project.glob('mirror.log*'):
            path.read_text()  # Ordinary UTF-8 lines stay intact in each file.
        arguments = self.invocations.read_text().splitlines()
        self.assertIn(str(self.project / 'compose.yaml'), arguments)

    def test_single_oversized_line_is_bounded(self) -> None:
        payload = b'x' * 600 + b'\n'
        self.assertEqual(self.run_job(payload).returncode, 0)
        self.assertTrue(payload.endswith(self.retained_output()))
        self.assertEqual(len(list(self.project.glob('mirror.log*'))), 4)

    def test_existing_oversized_log_is_trimmed_before_rotation(self) -> None:
        (self.project / 'mirror.log').write_bytes(b'old ' * 100)
        self.assertEqual(self.run_job(b'new\n').returncode, 0)
        self.assertTrue(self.retained_output().endswith(b'new\n'))

    def test_failed_compose_status_is_preserved_after_rotation(self) -> None:
        for args in ((), ('stars',)):
            with self.subTest(args=args):
                result = self.run_job(b'failure\n' * 40, exit_code=23, args=args)
                self.assertEqual(result.returncode, 23)
                self.assertTrue(self.retained_output().endswith(b'failure\n'))

    def test_overlapping_run_does_not_write_or_rotate_logs(self) -> None:
        log = self.project / 'mirror.log'
        log.write_bytes(b'unchanged\n')
        with self.lock.open('a') as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for script, args in (
                ('run-mirror.sh', ()),
                ('run-owned.sh', ()),
                ('run-stars.sh', ()),
                ('run-org.sh', ('go-gitea',)),
            ):
                with self.subTest(script=script):
                    result = self.run_job(b'not written\n', script=script, args=args)
                    self.assertEqual(result.returncode, 0)
        self.assertFalse(self.invocations.exists())
        self.assertEqual(list(self.project.glob('mirror.log*')), [log])
        self.assertEqual(log.read_bytes(), b'unchanged\n')

    def test_log_write_failure_is_reported(self) -> None:
        (self.project / 'mirror.log').mkdir()
        self.assertNotEqual(self.run_job(b'cannot write\n').returncode, 0)

    def test_wrappers_select_the_requested_job_and_forward_options(self) -> None:
        for script, args, command in (
            ('run-owned.sh', (), ('owned',)),
            ('run-stars.sh', ('--workers', '3'), ('stars', '--workers', '3')),
            (
                'run-org.sh',
                ('go-gitea', '--no-mirror'),
                ('org', 'go-gitea', '--no-mirror'),
            ),
            (
                'run-mirror.sh',
                ('--section', 'gitea_private', 'org', 'go-gitea'),
                ('--section', 'gitea_private', 'org', 'go-gitea'),
            ),
        ):
            with self.subTest(script=script, args=args):
                self.invocations.write_text('')
                result = self.run_job(b'job output\n', script=script, args=args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    self.invocations.read_text().splitlines(),
                    [
                        'compose',
                        '--project-directory',
                        str(self.project),
                        '--file',
                        str(self.project / 'compose.yaml'),
                        'run',
                        '--rm',
                        '-T',
                        '--interactive=false',
                        'mirror',
                        *command,
                    ],
                )

    def test_default_cron_runner_uses_configured_compose_command(self) -> None:
        self.assertEqual(self.run_job(b'owned\n').returncode, 0)
        self.assertEqual(
            self.invocations.read_text().splitlines()[-5:],
            ['up', '--no-color', '--exit-code-from', 'mirror', 'mirror'],
        )

    def test_org_requires_a_name_before_starting_docker(self) -> None:
        for args in ((), ('',), ('--workers', '3')):
            with self.subTest(args=args):
                result = self.run_job(b'', script='run-org.sh', args=args)
                self.assertEqual(result.returncode, 2)
                self.assertIn(b'ORG_NAME', result.stderr)
                self.assertFalse(self.invocations.exists())

    def test_org_help_does_not_start_docker(self) -> None:
        result = self.run_job(b'', script='run-org.sh', args=('--help',))
        self.assertEqual(result.returncode, 0)
        self.assertIn(b'ORG_NAME', result.stdout)
        self.assertFalse(self.invocations.exists())


if __name__ == '__main__':
    unittest.main()
