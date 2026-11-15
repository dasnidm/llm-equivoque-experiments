"""Build a separate no-advertised-tool CLI catalogue for technical testing.

The exact catalogue bytes and output SHA must be frozen for any future use.
This is an operational profile change; do not alter an existing run or infer
that a loopback wire check proves provider-side behavior.
"""
import copy
import hashlib
import json
from pathlib import Path

REMOVED = ('tool_mode', 'multi_agent_version', 'apply_patch_tool_type')


def sanitize(value):
    if not isinstance(value, dict) or not isinstance(value.get('models'), list):
        raise ValueError('Expected a model catalogue')
    result = copy.deepcopy(value)
    slugs = [m.get('slug') for m in result['models']]
    if not slugs or any(not isinstance(x, str) or not x for x in slugs) or len(set(slugs)) != len(slugs):
        raise ValueError('Missing or duplicate model slug')
    for model in result['models']:
        for key in REMOVED:
            model.pop(key, None)
        model['node_repl_disabled'] = True
        model['experimental_supported_tools'] = []
    return result


def build(source, output):
    source, output = Path(source), Path(output)
    data = source.read_bytes()
    sanitized = (json.dumps(sanitize(json.loads(data)), ensure_ascii=False, sort_keys=True,
                            separators=(',', ':')) + '\n').encode()
    if output.exists():
        if output.read_bytes() != sanitized:
            raise FileExistsError('Existing catalogue differs; never overwrite it')
    else:
        output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with output.open('xb') as f:
            f.write(sanitized)
    return {'source_sha256': hashlib.sha256(data).hexdigest(),
            'sanitized_sha256': hashlib.sha256(sanitized).hexdigest()}


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True)
    p.add_argument('--output', required=True)
    print(json.dumps(build(p.parse_args().source, p.parse_args().output), indent=2))
