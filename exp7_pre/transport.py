"""Native isolated sessions with optional turn-level output schemas.

This module does not launch work on import. The experiment driver must pass
the frozen, supported model ID and effort. No transport-level retry occurs.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import signal
import subprocess
import time

from equivoque.core import ROOT
from equivoque.transport import overrides, provider_schema


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def subject_directory(raw_directory):
    """Stable opaque cwd, separated from researcher-visible raw artifacts.

    The model's injected environment metadata can include cwd and workspace
    root. Do not expose run, model, arm, or experiment names in that path.
    This only constructs a path; the caller creates the directory on request.
    """
    opaque=hashlib.sha256(str(Path(raw_directory).resolve()).encode()).hexdigest()[:24]
    return ROOT.parent/'work'/'native-study'/opaque/'subject'


HOST_DISABLED_NOTICE = ('Code Mode is unavailable because code-mode host is disabled. '
                        'Code mode will fail closed; enable `features.code_mode_host` '
                        'and install `codex-code-mode-host`.')


def startup_notices(events):
    """This CLI emits one local tool-disable notice before the subject turn.

    Recognize only its exact text and only before turn.started. This does not
    permit an error or tool invocation during the subject's response.
    """
    starts = [i for i,e in enumerate(events) if e.get('type') == 'turn.started']
    if len(starts) != 1:
        return []
    prefix = events[:starts[0]]
    threads = [i for i,e in enumerate(prefix) if e.get('type') == 'thread.started']
    if not threads:
        return []
    notices = []
    for event in prefix[threads[-1]+1:]:
        item = event.get('item', {})
        if (event.get('type') == 'item.completed' and item.get('type') == 'error'
                and item.get('message') == HOST_DISABLED_NOTICE):
            notices.append(event)
    return notices[:1]


def recovered_transport_notices(events):
    """Recognize the native CLI retry/fallback diagnostics of a completed turn.

    This is *classification of a returned CLI stream*, not a separate request,
    retry policy, change of endpoint, or assertion about provider executions.
    Only exact diagnostic prefixes with a nonempty reason are recognized;
    native retry counters can reset when a fallback transport is used. Every
    other error, tool item, or malformed event ordering remains a failure. All
    original raw events and reasons are retained separately.
    """
    starts=[i for i,e in enumerate(events) if e.get('type')=='turn.started']
    ends=[i for i,e in enumerate(events) if e.get('type')=='turn.completed']
    messages=[i for i,e in enumerate(events) if e.get('type')=='item.completed' and e.get('item',{}).get('type')=='agent_message']
    if len(starts)!=1 or len(ends)!=1 or len(messages)!=1:
        return []
    retry_pattern=re.compile(r'Reconnecting\.\.\. [1-5]/5 \(([\s\S]+)\)')
    fallback_prefix='Falling back from WebSockets to HTTPS transport. '
    target=[]
    for i,e in enumerate(events):
        if e.get('type')=='error':
            match=retry_pattern.fullmatch(str(e.get('message','')))
            if match and match.group(1).strip():target.append(i)
        elif e.get('type')=='item.completed' and e.get('item',{}).get('type')=='error':
            text=e['item'].get('message','')
            if isinstance(text,str) and text.startswith(fallback_prefix) and text[len(fallback_prefix):].strip():target.append(i)
    if not target or not all(starts[0]<i<messages[0]<ends[0] for i in target):
        return []
    accepted={id(e) for e in startup_notices(events)}|{id(events[i]) for i in target}
    for e in events:
        ty=e.get('type','')
        if ty in ('error','turn.failed','thread.failed') and id(e) not in accepted:return []
        if str(ty).startswith('item.') and e.get('item',{}).get('type') not in ('reasoning','agent_message') and id(e) not in accepted:return []
    return [events[i] for i in target]


def https_fallback_in_recovery(events):
    notices=recovered_transport_notices(events)
    return any(e.get('type')=='item.completed' and e.get('item',{}).get('type')=='error'
               and str(e.get('item',{}).get('message','')).startswith('Falling back from WebSockets to HTTPS transport. ')
               for e in notices)


def unexpected_items(events):
    """Fail closed: model-facing sessions have no tools or plan capability."""
    allowed = {'reasoning', 'agent_message'}
    notices = {id(e) for e in startup_notices(events)+recovered_transport_notices(events)}
    return [e for e in events if str(e.get('type','')).startswith('item.')
            and e.get('item',{}).get('type') not in allowed and id(e) not in notices]


def failure_events(events):
    notices = {id(e) for e in recovered_transport_notices(events)}
    failures = [e for e in events if e.get('type') in ('error','turn.failed','thread.failed') and id(e) not in notices]
    if sum(e.get('type') == 'turn.started' for e in events) != 1:
        failures.append({'type':'missing_or_duplicate_turn_start'})
    return failures


def command_for(trial, system_path, subject, session_id, schema_path):
    command = ['codex', 'exec']
    if session_id:
        command.append('resume')
    command += ['--ignore-user-config', '--ignore-rules', '--skip-git-repo-check',
                '--json', '--model', trial['model']]
    if schema_path is not None:
        command += ['--output-schema', str(Path(schema_path).resolve())]
    command += overrides(system_path, trial['effort'])
    if session_id:
        command += [session_id, '-']
    else:
        command += ['--sandbox', 'read-only', '-C', str(Path(subject).resolve()), '-']
    return command


class NativeTransport:
    name = 'codex-native-optional-schema'

    def __init__(self, timeout=300):
        if timeout <= 0:
            raise ValueError('timeout must be positive')
        self.timeout = timeout

    def request(self, trial, prompt, schema, system, session_id, directory, turn):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        subject = subject_directory(directory)
        subject.mkdir(parents=True, exist_ok=True)
        os.chmod(subject, 0o700)
        system_path = directory/'subject-system.txt'
        if system_path.exists():
            if system_path.read_text() != system:
                raise ValueError('A session cannot change its system instruction')
        else:
            with system_path.open('x') as f:
                f.write(system); f.flush(); os.fsync(f.fileno())
        attempt_dir = directory/f'turn-{turn:02d}'
        # A prior attempt is never replaced or resumed by this transport.
        attempt_dir.mkdir(exist_ok=False)
        effective = provider_schema(schema) if schema is not None else None
        schema_path = None
        if effective is not None:
            schema_path = attempt_dir/'schema.json'
            with schema_path.open('x') as f:
                json.dump(effective, f, ensure_ascii=False); f.write('\n'); f.flush(); os.fsync(f.fileno())
        with (attempt_dir/'prompt.txt').open('x') as f:
            f.write(prompt); f.flush(); os.fsync(f.fileno())
        cmd = command_for(trial, system_path, subject, session_id, schema_path)
        stdout_path, stderr_path = attempt_dir/'events.jsonl', attempt_dir/'stderr.txt'
        timed_out = False
        start = time.monotonic()
        with stdout_path.open('x') as out, stderr_path.open('x') as err:
            process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=out, stderr=err,
                                       text=True, cwd=subject, start_new_session=True)
            try:
                process.communicate(prompt, timeout=self.timeout)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                timed_out = True
            out.flush(); os.fsync(out.fileno()); err.flush(); os.fsync(err.fileno())
        events, malformed = [], 0
        for line in stdout_path.read_text().splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                malformed += 1
        ids = [e['thread_id'] for e in events if e.get('type') == 'thread.started']
        messages = [e['item']['text'] for e in events if e.get('type') == 'item.completed'
                    and e.get('item', {}).get('type') == 'agent_message']
        usage = [e.get('usage') for e in events if e.get('type') == 'turn.completed']
        forbidden = unexpected_items(events)
        stderr = stderr_path.read_text()
        fallback = ('fallback metadata' in stderr.lower() or
                    any('fallback metadata' in str(e).lower() for e in events))
        compactions = sum('compact' in str(e.get('type','')).lower() for e in events)
        recovered = recovered_transport_notices(events)
        next_id = ids[-1] if ids else session_id
        ok = (process.returncode == 0 and not timed_out and len(messages) == 1 and bool(usage)
              and bool(next_id) and not forbidden and not malformed and not fallback
              and not failure_events(events)
              and (not session_id or next_id == session_id))
        files = [system_path, attempt_dir/'prompt.txt', stdout_path, stderr_path]
        if schema_path: files.append(schema_path)
        return {'ok': bool(ok), 'session_id': next_id, 'text': messages[-1] if messages else '',
                'events': events, 'stderr': stderr, 'command': cmd, 'exit_code': process.returncode,
                'timeout': timed_out, 'duration_seconds': time.monotonic()-start,
                'usage': usage[-1] if usage else None, 'tool_events': len(forbidden),
                'compaction_events': compactions, 'startup_notices': len(startup_notices(events)),
                'https_fallback':bool(https_fallback_in_recovery(events) and ok),'recovered_transport_events':len(recovered),
                'metadata_fallback': fallback, 'malformed_event_lines': malformed,
                'provider_schema': effective,
                'raw_files': [{'path':str(p.resolve()), 'sha256':digest(p)} for p in files]}
