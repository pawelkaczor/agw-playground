"""Black-box contract tests. Run inside the Compose test service."""
import copy
import fcntl
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('/artifacts')
ACTIVE = Path('/scenarios/active.json')
GATEWAY = 'http://gateway:3000/v1/chat/completions'
PASS = {'action': 'pass'}
REQ_MASK = {'action': 'mask', 'replacements': [{'from': 'REQUEST_SECRET', 'to': '[REQUEST_MASKED]'}]}
RES_MASK = {'action': 'mask', 'replacements': [{'from': 'RESPONSE_SECRET', 'to': '[RESPONSE_MASKED]'}]}
REJECT = {'action': 'reject', 'statusCode': 451, 'body': 'Blocked by test policy.', 'reason': 'test'}
MESSAGES = [{'role': 'system', 'content': 'Keep this instruction.'},
            {'role': 'user', 'content': 'My value is REQUEST_SECRET.'}]
CHOICES = ['Mock reply contains RESPONSE_SECRET.']


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def activate(value):
    temporary = ACTIVE.with_suffix('.tmp')
    write_json(temporary, value)
    os.replace(temporary, ACTIVE)


def exchange(url, body=None):
    headers = {'Content-Type': 'application/json'} if body is not None else {}
    request = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(), headers=headers)
    try:
        response = urllib.request.urlopen(request, timeout=15)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        raw = response.read().decode()
        try:
            decoded = json.loads(raw)
        except ValueError:
            decoded = raw
        return {'status': response.status, 'headers': dict(response.headers), 'body': decoded, 'rawBody': raw}


def ready():
    for url, expected in [('http://guardrails:8080/health', 200), ('http://mock:8000/health', 200),
                          ('http://gateway:3000/health', 404)]:
        deadline = time.monotonic() + 90
        while True:
            try:
                result = exchange(url)
                if result['status'] == expected:
                    break
            except (OSError, urllib.error.URLError):
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError('Readiness timeout: ' + url)
            time.sleep(0.5)


def journal(name):
    path = ROOT / (name + '.jsonl')
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def changed(text, mode):
    if mode.get('action') == 'mask':
        for replacement in mode['replacements']:
            text = text.replace(replacement['from'], replacement['to'])
    return text


def equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f'{label}: expected {expected!r}, observed {actual!r}')


def cases():
    result = []
    def add(name, request=PASS, response=PASS, messages=MESSAGES, choices=CHOICES,
            failure_stage=None, reject_stage=None, service_error=False):
        result.append(dict(name=name, scenario={'request': request, 'response': response, 'mock': {'choices': choices}},
                           messages=messages, failure_stage=failure_stage, reject_stage=reject_stage,
                           service_error=service_error))
    add('pass-pass')
    add('pass-with-reasons', {'action': 'pass', 'reason': 'request ok'}, {'action': 'pass', 'reason': 'response ok'})
    add('mask-request', REQ_MASK)
    add('mask-response', response=RES_MASK)
    add('mask-both', REQ_MASK, RES_MASK)
    add('reject-request', REJECT, reject_stage='request')
    add('reject-response', response=REJECT, reject_stage='response')
    add('multiple-messages-and-choices', REQ_MASK, RES_MASK,
        [{'role': 'system', 'content': 'REQUEST_SECRET system'},
         {'role': 'user', 'content': 'REQUEST_SECRET one'},
         {'role': 'assistant', 'content': 'Unchanged assistant history'},
         {'role': 'user', 'content': 'two REQUEST_SECRET REQUEST_SECRET'}],
        ['first RESPONSE_SECRET', 'second RESPONSE_SECRET', 'unchanged third'])
    add('unicode-and-empty',
        {'action': 'mask', 'replacements': [{'from': 'żółć🔒', 'to': '匿名'}, {'from': 'DELETE', 'to': ''}]},
        {'action': 'mask', 'replacements': [{'from': '秘密🔒', 'to': 'zażółć'}, {'from': 'DELETE', 'to': ''}]},
        [{'role': 'user', 'content': 'żółć🔒 DELETE'}, {'role': 'user', 'content': 'DELETE'}],
        ['秘密🔒 DELETE', 'DELETE'])
    for stage in ['request', 'response']:
        correct_body = ({'messages': [{'role': 'user', 'content': '[MASKED]', 'name': 'extra'}]}
                        if stage == 'request' else
                        {'choices': [{'message': {'role': 'assistant', 'content': '[MASKED]', 'name': 'extra'}}]})
        wrong_body = ({'choices': [{'message': {'role': 'assistant', 'content': '[MASKED]'}}]}
                      if stage == 'request' else {'messages': [{'role': 'user', 'content': '[MASKED]'}]})
        for name, action in [
            ('bare-array-mask', {'body': [{'role': 'user', 'content': '[MASKED]'}], 'reason': 'original Java shape'}),
            ('wrong-wrapper', {'body': wrong_body}),
            ('extra-message-field', {'body': correct_body}),
            ('unexpected-pass-field', {'reason': 'ok', 'score': 0.99}),
        ]:
            add(f'{name}-{stage}', **{stage: {'rawReply': {'action': action}}}, failure_stage=stage)
        add(f'invalid-scenario-{stage}', **{stage: {'action': 'unknown'}}, failure_stage=stage, service_error=True)
    return result


def run_case(case, directory):
    settings = case['scenario']
    request = {'model': 'local-test', 'messages': case['messages'], 'stream': False,
               'temperature': 0.2, 'n': len(settings['mock']['choices'])}
    before_guard = len(journal('guardrails'))
    before_mock = len(journal('mock'))
    activate(settings)
    client = exchange(GATEWAY, request)
    guards = journal('guardrails')[before_guard:]
    mocks = journal('mock')[before_mock:]
    evidence = {'scenario': settings, 'clientRequest': request, 'clientResponse': client,
                'guardrailExchanges': guards, 'mockExchanges': mocks}
    write_json(directory / (case['name'] + '.json'), evidence)
    stopped = case['failure_stage'] or case['reject_stage']
    equal([g['stage'] for g in guards], ['request'] if stopped == 'request' else ['request', 'response'], 'webhook call sequence')
    equal(len(mocks), 0 if stopped == 'request' else 1, 'upstream call count')
    equal(guards[0]['requestBody'], {'body': {'messages': case['messages']}}, 'normalized request webhook body')
    for g in guards:
        equal(g['responseStatus'], 500 if case['service_error'] and g['stage'] == stopped else 200, 'webhook HTTP status')
    if mocks:
        expected_messages = [{**message, 'content': changed(message['content'], settings['request'])} for message in case['messages']]
        equal(mocks[0]['requestBody']['messages'], expected_messages, 'exact upstream messages')
        for field in ['model', 'stream', 'temperature', 'n']:
            equal(mocks[0]['requestBody'].get(field), request[field], 'preserved request ' + field)
        normalized = {'body': {'choices': [{'message': c['message']} for c in mocks[0]['responseBody']['choices']]}}
        equal(guards[-1]['requestBody'], normalized, 'normalized response webhook body')
    if case['failure_stage']:
        equal(client['status'], 503, 'fail-closed client status')
        equal(client['rawBody'], 'failed to process LLM ' + case['failure_stage'], 'fail-closed body')
    elif case['reject_stage']:
        equal(client['status'], 451, 'client rejection status')
        equal(client['rawBody'], REJECT['body'], 'client rejection body')
    else:
        equal(client['status'], 200, 'client success status')
        expected = copy.deepcopy(mocks[0]['responseBody'])
        for choice in expected['choices']:
            choice['message']['content'] = changed(choice['message']['content'], settings['response'])
        equal(client['body'], expected, 'complete client completion including metadata')
    return client['status']


def main():
    ROOT.mkdir(exist_ok=True)
    with (ROOT / 'test.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        original = ACTIVE.read_bytes()
        stamp = os.environ.get('LAB_RUN_ID') or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
        if not all(c.isalnum() or c in '.-_' for c in stamp):
            raise ValueError('LAB_RUN_ID must contain only letters, digits, dot, dash, or underscore')
        directory = ROOT / 'runs' / stamp
        directory.mkdir(parents=True, exist_ok=False)
        results = []
        try:
            ready()
            for case in cases():
                try:
                    status = run_case(case, directory)
                    entry = {'name': case['name'], 'passed': True, 'clientStatus': status}
                except Exception as error:
                    entry = {'name': case['name'], 'passed': False, 'error': str(error)}
                results.append(entry)
                print(('PASS ' if entry['passed'] else 'FAIL ') + entry['name'] + (': ' + entry['error'] if 'error' in entry else ''), flush=True)
        finally:
            temporary = ACTIVE.with_suffix('.tmp')
            temporary.write_bytes(original)
            os.replace(temporary, ACTIVE)
            summary = {'run': stamp, 'gatewayImage': 'cr.agentgateway.dev/agentgateway:v1.7.0',
                       'passed': sum(r['passed'] for r in results), 'total': len(results), 'results': results}
            write_json(directory / 'summary.json', summary)
            write_json(ROOT / 'latest.json', summary)
            report = ['# Webhook verification results', '', f"Run: `{stamp}`", '',
                      f"Passed: {summary['passed']}/{summary['total']}", '',
                      '| Test | Result | Observation |', '| --- | --- | --- |']
            for r in results:
                observation = 'HTTP ' + str(r['clientStatus']) if r['passed'] else r['error'].replace('|', '\\|').replace('\n', ' ')
                report.append(f"| {r['name']} | {'PASS' if r['passed'] else 'FAIL'} | {observation} |")
            report += ['', 'Each test JSON contains the scenario, client exchange, webhook exchanges, and mock exchanges.',
                       'Gateway logs and image metadata are saved by verify.sh in the same run directory.',
                       'Scope: non-streaming OpenAI chat completions, synthetic text, standalone route configuration.', '']
            (directory / 'report.md').write_text('\n'.join(report))
            (ROOT / 'report.md').write_text('\n'.join(report))
        print(f"Evidence: artifacts/runs/{stamp}")
        return 0 if len(results) == len(cases()) and all(r['passed'] for r in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
