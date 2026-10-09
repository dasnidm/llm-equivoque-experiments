"""Native Codex sessions in an empty directory, without subject tools."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time

DISABLED_FEATURES = (
    'shell_tool', 'unified_exec', 'apps', 'plugins', 'remote_plugin',
    'multi_agent', 'multi_agent_v2', 'code_mode_host', 'browser_use',
    'browser_use_external', 'computer_use', 'view_image', 'image_generation',
    'skill_search', 'sleep_tool', 'hooks', 'memories', 'workspace_dependencies',
    'unbounded_connection_retries', 'goals',
)


def overrides(system_path, effort):
    values = {
        'model_reasoning_effort': effort,
        'model_instructions_file': str(Path(system_path).resolve()),
        'project_doc_max_bytes': 0, 'developer_instructions': '',
        'web_search': 'disabled', 'include_apps_instructions': False,
        'include_collaboration_mode_instructions': False,
        'include_permissions_instructions': False,
        'skills.include_instructions': False, 'skills.bundled.enabled': False,
        'tools.update_plan.enabled': False,
        'tools.experimental_request_user_input.enabled': False,
        # This CLI's structured feature settings also carry default role hints.
        # A bare feature=false leaves those hints in the visible subject input.
        'features.multi_agent_v2.enabled': False,
        'features.multi_agent_v2.usage_hint_enabled': False,
        'features.multi_agent_v2.usage_hint_text': '',
        'features.multi_agent_v2.root_agent_usage_hint_text': '',
        'features.multi_agent_v2.subagent_usage_hint_text': '',
        'features.multi_agent_v2.multi_agent_mode_hint_text': '',
        'features.code_mode.enabled': False,
    }
    values.update({'features.' + feature: False
                   for feature in DISABLED_FEATURES if feature != 'multi_agent_v2'})
    result = []
    for key, value in values.items():
        result.extend(['-c', key + '=' + json.dumps(value)])
    return result


class CodexTransport:
    name = 'codex-native'

    def __init__(self, protocol, timeout=300):
        self.protocol = protocol
        self.timeout = timeout

    def request(self, trial, prompt, schema, session_id, directory, attempt):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        subject = directory / 'subject'
        subject.mkdir(exist_ok=True)
        os.chmod(subject, 0o700)
        system_path = directory / 'subject-system.txt'
        system_path.write_text(self.protocol.data['system'])
        schema_path = directory / f'turn-{attempt:02d}.schema.json'
        schema_path.write_text(json.dumps(schema) + '\n')
        command = ['codex', 'exec']
        if session_id:
            command.append('resume')
        command += ['--ignore-user-config', '--ignore-rules',
                    '--skip-git-repo-check', '--json', '--model', trial['model'],
                    '--output-schema', str(schema_path.resolve())]
        command += overrides(system_path, trial['effort'])
        if session_id:
            command += [session_id, '-']
        else:
            command += ['--sandbox', 'read-only', '-C', str(subject.resolve()), '-']
        start = time.monotonic()
        stdout_path = directory / f'turn-{attempt:02d}.events.jsonl'
        stderr_path = directory / f'turn-{attempt:02d}.stderr.txt'
        timed_out = False
        # Stream durably to disk. A killed/uncertain turn is never retried.
        with stdout_path.open('w') as out, stderr_path.open('w') as err:
            process = subprocess.Popen(command, stdin=subprocess.PIPE,
                                       stdout=out, stderr=err, text=True,
                                       cwd=subject, start_new_session=True)
            try:
                process.communicate(prompt, timeout=self.timeout)
            except subprocess.TimeoutExpired:
                import signal
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                timed_out = True
        events = []
        malformed_lines = 0
        for line in stdout_path.read_text().splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                malformed_lines += 1
        ids = [event['thread_id'] for event in events
               if event.get('type') == 'thread.started']
        messages = [event['item']['text'] for event in events
                    if event.get('type') == 'item.completed'
                    and event.get('item', {}).get('type') == 'agent_message']
        usage = [event.get('usage') for event in events
                 if event.get('type') == 'turn.completed']
        tools = [event.get('item', {}).get('type') for event in events
                 if event.get('type') in ('item.started', 'item.completed')
                 and event.get('item', {}).get('type') in
                 ('command_execution', 'mcp_tool_call', 'web_search',
                  'file_change', 'collab_agent_tool_call')]
        stderr = stderr_path.read_text()
        metadata_fallback = ('fallback metadata' in stderr.lower() or
            any('fallback metadata' in str(event).lower() for event in events))
        next_id = ids[-1] if ids else session_id
        ok = (process.returncode == 0 and not timed_out and len(messages) == 1
              and bool(usage) and bool(next_id) and not tools
              and not malformed_lines and not metadata_fallback
              and (not session_id or next_id == session_id))
        return {
            'ok': ok, 'session_id': next_id,
            'text': messages[-1] if messages else '',
            'events': events, 'stderr': stderr,
            'command': command, 'exit_code': process.returncode,
            'timeout': timed_out, 'duration_seconds': time.monotonic() - start,
            'usage': usage[-1] if usage else None,
            'tool_events': tools, 'metadata_fallback': metadata_fallback,
            'malformed_event_lines': malformed_lines,
        }
