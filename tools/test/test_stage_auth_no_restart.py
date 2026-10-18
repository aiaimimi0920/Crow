import hashlib

import pytest

from tools import pc2_auth_recovery as pc2
from tools.pc1_desktop_recovery import recovery_phase
from tools.test.test_stage_auth_recovery import recovery


@pytest.mark.parametrize('probe', ['valid', 'challenge', 'unavailable', 'phase_rejected'])
def test_scoped_snapshot_is_verified_without_browser_restart(tmp_path, monkeypatch, probe):
    manager, _ = recovery(tmp_path)
    snapshot = tmp_path / 'cookie.json'
    snapshot.write_text('[{"name":"cookie2","value":"fixture","domain":".taobao.com"}]')
    digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    with manager._locked_state():
        manager._state['active']['status'] = 'snapshot_ready'
        manager._state['active']['snapshot']['sha256'] = digest
        manager._persist_locked()
    token = tmp_path / 'token'
    token.write_text('fixture-recovery-token', encoding='utf-8')
    imports = []
    def import_snapshot(*args, **kwargs):
        imports.append(True)
        return {'sha256': digest, 'cookie_count': 1}
    monkeypatch.setattr(pc2, 'import_cookie_snapshot_to_cdp', import_snapshot)
    def check(*args):
        if probe == 'unavailable': raise OSError('sensitive network diagnostic')
        return probe == 'valid'
    monkeypatch.setattr(pc2, 'probe_seed_access', check)
    calls, cleared = [], []
    def post(url, payload, **kwargs):
        calls.append(url.rsplit('/', 1)[-1])
        if url.endswith('/heartbeat'): return {'ok': True}
        if url.endswith('/claim'): return manager.claim('pc2', payload['recovery_id'], 'pc2', now=7)
        if url.endswith('/pc2_restarting'):
            return {'ok': False} if probe == 'phase_rejected' else manager.pc2_restarting(payload['recovery_id'], now=8)
        assert url.endswith('/result')
        return manager.accept_stage_result(payload, validate_and_clear=lambda a: cleared.append(a['scope']), captured_count=10, now=9)
    def execute():
        return pc2.process_nas_auth_recovery_once('http://fixture/api', 'http://fixture/cdp', 'pc2',
            snapshot, tmp_path / 'marker', token, fetcher=lambda *a, **k: {'auth_recovery': manager.snapshot(now=6)}, poster=post)
    if probe == 'phase_rejected':
        with pytest.raises(OSError, match='verification phase'):
            execute()
        assert calls == ['heartbeat', 'claim', 'pc2_restarting']
        assert not cleared
        return
    result = execute()
    assert calls == ['heartbeat', 'claim', 'pc2_restarting', 'result']
    assert len(imports) == 1
    assert result['action'] == ('recovery_confirmed' if probe == 'valid' else 'recovery_failed')
    assert cleared == (['seed'] if probe == 'valid' else [])
    reason = {'valid': 'seed_payload_verified', 'challenge': 'stage_probe_failed', 'unavailable': 'stage_probe_unavailable'}[probe]
    state = manager.snapshot(now=10)
    assert state['last_result']['reason'] == reason
    if probe != 'valid':
        assert recovery_phase(state, state['last_result']['recovery_id'], scope='seed')['code'] == reason
