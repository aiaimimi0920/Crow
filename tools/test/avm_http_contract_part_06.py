from __future__ import annotations

from tools.test.avm_http_contract_context import *  # noqa: F401,F403


class AVMHttpContractPart06:
    def test_archive_detail_replay_post_endpoint(self):
        archive_dir = os.path.join(self.data_dir, 'archive', '2026')
        os.makedirs(archive_dir, exist_ok=True)
        recent_file = os.path.join(archive_dir, '2026-03-05.json')
        with open(recent_file, 'w', encoding='utf-8') as f:
            json.dump([{'id': 9301, '交易时间': '2026-03-05 10:00:00', '成交价格': '100万', '起拍价格': '80万', '建筑面积': '100㎡', '是否成交': True}], f, ensure_ascii=False)
        (status, payload) = self._post_collection_job('/api/avm/archive_detail_replay', {'window_days': 30, 'limit': 10, 'dry_run': False})
        self.assertEqual(status, 202)
        self.assertEqual(payload['prepared_count'], 1)

    def test_recent_enrich_maintenance_endpoint(self):
        archive_dir = os.path.join(self.data_dir, 'archive', '2026')
        os.makedirs(archive_dir, exist_ok=True)
        detail_dir = os.path.join(self.data_dir, 'html_archive', '2026', '2026-03-05')
        os.makedirs(detail_dir, exist_ok=True)
        detail_path = os.path.join(detail_dir, 'item-9001.html')
        with open(detail_path, 'w', encoding='utf-8') as f:
            f.write('<html><script>var center=[121.5001,31.2002];</script></html>')
        recent_file = os.path.join(archive_dir, '2026-03-05.json')
        with open(recent_file, 'w', encoding='utf-8') as f:
            json.dump([{'id': 9001, '交易时间': '2026-03-05 10:00:00', '成交价格': '100万', '起拍价格': '80万', '建筑面积': '100㎡', '城市': '上海市', '区': '浦东新区', 'detail_captured': True, 'detail_archive_path': 'html_archive/2026/2026-03-05/item-9001.html'}], f, ensure_ascii=False)
        (status, payload) = self._post_collection_job('/api/avm/recent_enrich_maintenance', {'window_days': 7, 'archive_limit': 20, 'sample_limit': 5, 'dry_run': False, 'extract_risk': False})
        self.assertEqual(status, 202)
        self.assertIn('before', payload)
        self.assertIn('after', payload)
        self.assertEqual(payload['archived_detail_backfill']['updated_records'], 1)
        with open(recent_file, 'r', encoding='utf-8') as f:
            saved = json.load(f)
        self.assertEqual(saved[0]['latitude'], 31.2002)
        self.assertEqual(saved[0]['longitude'], 121.5001)

    def test_recent_enrich_maintenance_can_prepare_replay(self):
        archive_dir = os.path.join(self.data_dir, 'archive', '2026')
        os.makedirs(archive_dir, exist_ok=True)
        recent_file = os.path.join(archive_dir, '2026-03-05.json')
        with open(recent_file, 'w', encoding='utf-8') as f:
            json.dump([{'id': 9201, '交易时间': '2026-03-05 10:00:00', '成交价格': '100万', '起拍价格': '80万', '建筑面积': '100㎡', 'detail_captured': True, '原始网站': 'https://sf-item.taobao.com/sf_item/9201.htm'}], f, ensure_ascii=False)
        (status, payload) = self._post_collection_job('/api/avm/recent_enrich_maintenance', {'window_days': 7, 'archive_limit': 10, 'sample_limit': 5, 'replay_limit': 10, 'dry_run': False, 'extract_risk': False, 'prepare_replay': True})
        self.assertEqual(status, 202)
        self.assertEqual(payload['detail_replay_preparation']['prepared_count'], 1)

    def test_collection_detail_maintenance_alias_endpoint(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.run_maintenance.return_value = {'before': {'detail_missing': 2}, 'after': {'detail_missing': 1}, 'archived_detail_backfill': {'updated_records': 1}}
            mocked_factory.return_value = fake_service
            (status, payload) = self._post_collection_job('/api/collection/details/maintenance', {'window_days': 7, 'archive_limit': 20, 'sample_limit': 5, 'dry_run': True, 'extract_risk': False})
        self.assertEqual(status, 202)
        self.assertEqual(payload['archived_detail_backfill']['updated_records'], 1)
        fake_service.run_maintenance.assert_called_once()

    def test_recent_enrich_maintenance_endpoint_rejects_invalid_json(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/avm/recent_enrich_maintenance', data=b'{', headers={'Content-Type': 'application/json', 'X-FAPAI-Control-Token': 'test-operator'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_INVALID_JSON')

    def test_collection_detail_maintenance_alias_rejects_invalid_json(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/collection/details/maintenance', data=b'{', headers={'Content-Type': 'application/json', 'X-FAPAI-Control-Token': 'test-operator'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_INVALID_JSON')

    def test_collection_detail_maintenance_alias_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.run_maintenance.side_effect = RuntimeError('boom')
            mocked_factory.return_value = fake_service
            req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/collection/details/maintenance', data=json.dumps({'window_days': 7, 'dry_run': True}).encode('utf-8'), headers={'Content-Type': 'application/json', 'X-FAPAI-Control-Token': 'test-operator'}, method='POST')
            with urllib.request.urlopen(req) as resp:
                accepted = json.loads(resp.read().decode('utf-8'))
            self._assert_collection_job_failed(resp.status, accepted, 'AVM_RECENT_ENRICH_MAINTENANCE_FAILED')

    def test_fetch_missing_detail_archives_endpoint(self):
        with mock.patch('src.collection.detail_archive_fetch.fetch_missing_detail_archives') as mocked_fetch:
            mocked_fetch.return_value = {'limit': 1, 'timeout': 9, 'dry_run': True, 'candidate_count': 2, 'fetched_count': 1, 'failed_count': 0, 'blocked_count': 1, 'touched_files': 0, 'samples': [{'item_id': 'x-1'}]}
            (status, payload) = self._post_collection_job('/api/avm/fetch_missing_detail_archives', {'limit': 1, 'timeout': 9, 'dry_run': True})
        self.assertEqual(status, 202)
        self.assertEqual(payload['candidate_count'], 2)
        self.assertEqual(payload['fetched_count'], 1)
        self.assertEqual(payload['blocked_count'], 1)

    def test_fetch_missing_detail_archives_endpoint_rejects_invalid_json(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/avm/fetch_missing_detail_archives', data=b'{', headers={'Content-Type': 'application/json', 'X-FAPAI-Control-Token': 'test-operator'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_INVALID_JSON')

    def test_fetch_missing_detail_archives_post_body_endpoint(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.fetch_missing_archives.return_value = {'limit': 2, 'timeout': 11, 'dry_run': True, 'candidate_count': 3, 'fetched_count': 1, 'failed_count': 1, 'blocked_count': 1}
            mocked_factory.return_value = fake_service
            (status, payload) = self._post_collection_job('/api/avm/fetch_missing_detail_archives', {'limit': '2', 'timeout': '11', 'dry_run': True, 'extract_risk': False})
        self.assertEqual(status, 202)
        self.assertEqual(payload['candidate_count'], 3)
        self.assertEqual(payload['fetched_count'], 1)
        self.assertEqual(payload['blocked_count'], 1)
        fake_service.fetch_missing_archives.assert_called_once_with(limit=2, timeout=11, extract_risk=False, dry_run=True)

    def test_fetch_missing_detail_archives_post_body_endpoint_defaults_invalid_numeric_body_fields(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.fetch_missing_archives.return_value = {'limit': 20, 'timeout': 15, 'dry_run': True, 'candidate_count': 0, 'fetched_count': 0, 'failed_count': 0, 'blocked_count': 0}
            mocked_factory.return_value = fake_service
            (status, payload) = self._post_collection_job('/api/avm/fetch_missing_detail_archives', {'limit': 'bad', 'timeout': 'bad', 'dry_run': 'maybe', 'extract_risk': 'maybe'})
        self.assertEqual(status, 202)
        self.assertEqual(payload['limit'], 20)
        self.assertEqual(payload['timeout'], 15)
        fake_service.fetch_missing_archives.assert_called_once_with(limit=20, timeout=15, extract_risk=True, dry_run=True)

    def test_fetch_missing_detail_archives_post_body_endpoint_clamps_negative_body_fields(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.fetch_missing_archives.return_value = {'limit': 0, 'timeout': 15, 'dry_run': True, 'candidate_count': 0, 'fetched_count': 0, 'failed_count': 0, 'blocked_count': 0}
            mocked_factory.return_value = fake_service
            (status, payload) = self._post_collection_job('/api/avm/fetch_missing_detail_archives', {'limit': '-1', 'timeout': '-1', 'dry_run': 'maybe', 'extract_risk': 'maybe'})
        self.assertEqual(status, 202)
        self.assertEqual(payload['limit'], 0)
        self.assertEqual(payload['timeout'], 15)
        fake_service.fetch_missing_archives.assert_called_once_with(limit=0, timeout=15, extract_risk=True, dry_run=True)

    def test_fetch_missing_detail_archives_post_body_endpoint_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.fetch_missing_archives.side_effect = RuntimeError('boom')
            mocked_factory.return_value = fake_service
            status, accepted = self._post_json('/api/avm/fetch_missing_detail_archives', {'limit': '2', 'timeout': '11', 'dry_run': True, 'extract_risk': False})
            self._assert_collection_job_failed(status, accepted, 'AVM_FETCH_MISSING_DETAIL_ARCHIVES_FAILED')

    def test_collection_detail_fetch_missing_alias_rejects_invalid_json(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/collection/details/fetch_missing', data=b'{', headers={'Content-Type': 'application/json', 'X-FAPAI-Control-Token': 'test-operator'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_INVALID_JSON')

    def test_collection_detail_fetch_missing_post_body_alias_endpoint(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.fetch_missing_archives.return_value = {'limit': 1, 'timeout': 9, 'dry_run': True, 'candidate_count': 2, 'fetched_count': 1, 'failed_count': 0, 'blocked_count': 1}
            mocked_factory.return_value = fake_service
            (status, payload) = self._post_collection_job('/api/collection/details/fetch_missing', {'limit': '1', 'timeout': '9', 'dry_run': True, 'extract_risk': False})
        self.assertEqual(status, 202)
        self.assertEqual(payload['candidate_count'], 2)
        self.assertEqual(payload['fetched_count'], 1)
        self.assertEqual(payload['blocked_count'], 1)
        fake_service.fetch_missing_archives.assert_called_once_with(limit=1, timeout=9, extract_risk=False, dry_run=True)

    def test_collection_detail_fetch_missing_post_body_alias_defaults_invalid_numeric_body_fields(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.fetch_missing_archives.return_value = {'limit': 20, 'timeout': 15, 'dry_run': True, 'candidate_count': 0, 'fetched_count': 0, 'failed_count': 0, 'blocked_count': 0}
            mocked_factory.return_value = fake_service
            (status, payload) = self._post_collection_job('/api/collection/details/fetch_missing', {'limit': 'bad', 'timeout': 'bad', 'dry_run': 'maybe', 'extract_risk': 'maybe'})
        self.assertEqual(status, 202)
        self.assertEqual(payload['limit'], 20)
        self.assertEqual(payload['timeout'], 15)
        fake_service.fetch_missing_archives.assert_called_once_with(limit=20, timeout=15, extract_risk=True, dry_run=True)

    def test_collection_detail_fetch_missing_post_body_alias_clamps_negative_body_fields(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.fetch_missing_archives.return_value = {'limit': 0, 'timeout': 15, 'dry_run': True, 'candidate_count': 0, 'fetched_count': 0, 'failed_count': 0, 'blocked_count': 0}
            mocked_factory.return_value = fake_service
            (status, payload) = self._post_collection_job('/api/collection/details/fetch_missing', {'limit': '-1', 'timeout': '-1', 'dry_run': 'maybe', 'extract_risk': 'maybe'})
        self.assertEqual(status, 202)
        self.assertEqual(payload['limit'], 0)
        self.assertEqual(payload['timeout'], 15)
        fake_service.fetch_missing_archives.assert_called_once_with(limit=0, timeout=15, extract_risk=True, dry_run=True)

    def test_collection_detail_fetch_missing_post_body_alias_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.fetch_missing_archives.side_effect = RuntimeError('boom')
            mocked_factory.return_value = fake_service
            status, accepted = self._post_json('/api/collection/details/fetch_missing', {'limit': '1', 'timeout': '9', 'dry_run': True, 'extract_risk': False})
            self._assert_collection_job_failed(status, accepted, 'AVM_FETCH_MISSING_DETAIL_ARCHIVES_FAILED')

    def test_collection_detail_fetch_missing_alias_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.fetch_missing_archives.side_effect = RuntimeError('boom')
            mocked_factory.return_value = fake_service
            req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/collection/details/fetch_missing', data=json.dumps({'limit': 1, 'timeout': 9, 'dry_run': True}).encode('utf-8'), headers={'Content-Type': 'application/json', 'X-FAPAI-Control-Token': 'test-operator'}, method='POST')
            with urllib.request.urlopen(req) as resp:
                accepted = json.loads(resp.read().decode('utf-8'))
            self._assert_collection_job_failed(resp.status, accepted, 'AVM_FETCH_MISSING_DETAIL_ARCHIVES_FAILED')

    def test_collection_seed_next_task_endpoint(self):
        fake_service = mock.Mock()
        fake_service.next_task.return_value = {'task': {'url': 'https://x/task'}, 'message': 'ok'}
        with mock.patch.object(server_module, '_seed_collection_service', return_value=fake_service):
            (status, payload) = self._post_json('/api/collection/seeds/next_task', {'session_id': 's-1'})
        self.assertEqual(status, 200)
        self.assertEqual(payload['task']['url'], 'https://x/task')
        fake_service.next_task.assert_called_once()

    def test_collection_seed_next_task_alias_returns_empty_task_payload_when_no_task_available(self):
        fake_service = mock.Mock()
        fake_service.next_task.return_value = {'task': None, 'message': '所有嗅探任务已完成'}
        with mock.patch.object(server_module, '_seed_collection_service', return_value=fake_service):
            (status, payload) = self._post_json('/api/collection/seeds/next_task', {'session_id': 's-1'})
        self.assertEqual(status, 200)
        self.assertEqual(payload, {'task': None, 'message': '所有嗅探任务已完成'})
        fake_service.next_task.assert_called_once_with('s-1', paused=False)

    def test_collection_seed_next_task_alias_passes_paused_state(self):
        fake_service = mock.Mock()
        fake_service.next_task.return_value = {'task': {}, 'message': 'ok'}
        original_paused = server_module.RUNTIME.control.paused
        server_module.RUNTIME.control.paused = True
        try:
            with mock.patch.object(server_module, '_seed_collection_service', return_value=fake_service):
                (status, payload) = self._post_json('/api/collection/seeds/next_task', {'session_id': 's-1'})
        finally:
            server_module.RUNTIME.control.paused = original_paused
        self.assertEqual(status, 200)
        self.assertEqual(payload['message'], 'ok')
        fake_service.next_task.assert_called_once_with('s-1', paused=True)

    def test_collection_seed_next_task_alias_treats_force_unlock_flag_as_paused(self):
        fake_service = mock.Mock()
        fake_service.next_task.return_value = {'task': {}, 'message': 'ok'}
        original_paused = server_module.RUNTIME.control.paused
        original_data_dir = server_module.DATA_DIR
        server_module.RUNTIME.control.paused = False
        server_module.DATA_DIR = self.data_dir
        flag_path = os.path.join(self.data_dir, 'force_unlock.flag')
        with open(flag_path, 'w', encoding='utf-8') as f:
            f.write('manual verification required')
        try:
            with mock.patch.object(server_module, '_seed_collection_service', return_value=fake_service):
                (status, payload) = self._post_json('/api/collection/seeds/next_task', {'session_id': 's-1'})
        finally:
            server_module.DATA_DIR = original_data_dir
            server_module.RUNTIME.control.paused = original_paused
        self.assertEqual(status, 200)
        self.assertEqual(payload['message'], 'ok')
        fake_service.next_task.assert_called_once_with('s-1', paused=True)

    def test_collection_seed_next_task_alias_returns_json_error_on_failure(self):
        fake_service = mock.Mock()
        fake_service.next_task.side_effect = RuntimeError('boom')
        with mock.patch.object(server_module, '_seed_collection_service', return_value=fake_service):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self._open_post('/api/collection/seeds/next_task', {'session_id': 's-1'})
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_SEED_NEXT_TASK_FAILED')
        self.assertRegex(body['error']['details']['error_id'], r'^[a-f0-9]{16}$')

    def test_collection_seed_report_progress_alias_endpoint(self):
        fake_service = mock.Mock()
        fake_service.report_progress.return_value = {'status': 'ok', 'updated': True}
        with mock.patch.object(server_module, '_seed_collection_service', return_value=fake_service):
            (status, payload) = self._post_json('/api/collection/seeds/report_progress', {'url': 'https://x/list', 'page': 2, 'has_next': True, 'total_pages': 5, 'zero_bid_detected': False})
        self.assertEqual(status, 200)
        self.assertEqual(payload['status'], 'ok')
        fake_service.report_progress.assert_called_once()

    def test_collection_seed_report_progress_alias_requires_url(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/collection/seeds/report_progress', data=json.dumps({'page': 2, 'has_next': True}).encode('utf-8'), headers={'Content-Type': 'application/json', 'X-FAPAI-Control-Token': 'test-operator'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_SEED_PROGRESS_MISSING_URL')

    def test_collection_seed_report_progress_accepts_generic_task_identity(self):
        fake_service = mock.Mock()
        fake_service.report_progress.return_value = {'status': 'ok'}
        payload = {'task_key': 'source:catalog:test', 'session_id': 'worker-1', 'page_num': 2, 'has_next': False}
        with mock.patch.object(server_module, '_seed_collection_service', return_value=fake_service):
            (status, body) = self._post_json('/api/collection/seeds/report_progress', payload)
        self.assertEqual(status, 200)
        self.assertEqual(body, {'status': 'ok'})
        fake_service.report_progress.assert_called_once_with(payload)

    def test_collection_seed_report_progress_maps_service_validation_to_400(self):
        fake_service = mock.Mock()
        fake_service.report_progress.side_effect = ValueError('requires task_key')
        payload = {'url': 'https://catalog.example/products', 'has_next': True}
        with mock.patch.object(server_module, '_seed_collection_service', return_value=fake_service):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self._post_json('/api/collection/seeds/report_progress', payload)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_SEED_PROGRESS_INVALID')

    def test_collection_seed_report_progress_alias_returns_500_on_invalid_json(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/collection/seeds/report_progress', data=b'{', headers={'Content-Type': 'application/json', 'X-FAPAI-Control-Token': 'test-operator'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_INVALID_JSON')

    def test_collection_seed_report_progress_alias_returns_json_error_on_failure(self):
        fake_service = mock.Mock()
        fake_service.report_progress.side_effect = RuntimeError('boom')
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/collection/seeds/report_progress', data=json.dumps({'url': 'https://x/list'}).encode('utf-8'), headers={'Content-Type': 'application/json', 'X-FAPAI-Control-Token': 'test-operator'}, method='POST')
        with mock.patch.object(server_module, '_seed_collection_service', return_value=fake_service):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_SEED_PROGRESS_FAILED')
        self.assertRegex(body['error']['details']['error_id'], r'^[a-f0-9]{16}$')

    def test_collection_seed_report_progress_legacy_endpoint(self):
        fake_service = mock.Mock()
        fake_service.report_progress.return_value = {'status': 'ok', 'updated': True}
        with mock.patch.object(server_module, '_seed_collection_service', return_value=fake_service):
            (status, payload) = self._post_json('/api/report_sniff_status', {'url': 'https://x/list', 'page': 2, 'has_next': True, 'total_pages': 5, 'zero_bid_detected': False})
        self.assertEqual(status, 200)
        self.assertEqual(payload['status'], 'ok')
        fake_service.report_progress.assert_called_once()

    def test_report_sniff_status_legacy_endpoint_requires_url(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/report_sniff_status', data=json.dumps({'page': 2, 'has_next': True}).encode('utf-8'), headers={'Content-Type': 'application/json', 'X-FAPAI-Control-Token': 'test-operator'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_SEED_PROGRESS_MISSING_URL')

    def test_report_sniff_status_legacy_endpoint_returns_500_on_invalid_json(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/report_sniff_status', data=b'{', headers={'Content-Type': 'application/json', 'X-FAPAI-Control-Token': 'test-operator'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_INVALID_JSON')

    def test_report_sniff_status_legacy_endpoint_returns_json_error_on_failure(self):
        fake_service = mock.Mock()
        fake_service.report_progress.side_effect = RuntimeError('boom')
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/report_sniff_status', data=json.dumps({'url': 'https://x/list'}).encode('utf-8'), headers={'Content-Type': 'application/json', 'X-FAPAI-Control-Token': 'test-operator'}, method='POST')
        with mock.patch.object(server_module, '_seed_collection_service', return_value=fake_service):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_SEED_PROGRESS_FAILED')
        self.assertRegex(body['error']['details']['error_id'], r'^[a-f0-9]{16}$')

    def test_collection_seed_batch_endpoint(self):
        with mock.patch.object(server_module, 'handle_seed_batch_submission', return_value={'status': 'ok', 'new': 2}) as mocked_save:
            (status, payload) = self._post_json('/api/collection/seeds/batch', {'items': [{'id': '1'}], 'source_page_url': 'https://sf.taobao.com/list/x?page=1'})
        self.assertEqual(status, 200)
        self.assertEqual(payload['new'], 2)
        mocked_save.assert_called_once()

    def test_collection_seed_batch_alias_returns_500_on_invalid_json(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/collection/seeds/batch', data=b'{', headers={'Content-Type': 'application/json', 'X-FAPAI-Control-Token': 'test-operator'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_INVALID_JSON')

    def test_collection_seed_batch_legacy_endpoint(self):
        with mock.patch.object(server_module, 'handle_seed_batch_submission', return_value={'status': 'ok', 'new': 2}) as mocked_save:
            (status, payload) = self._post_json('/api/save', {'items': [{'id': '1'}], 'source_page_url': 'https://sf.taobao.com/list/x?page=1'})
        self.assertEqual(status, 200)
        self.assertEqual(payload['new'], 2)
        mocked_save.assert_called_once()

    def test_save_legacy_endpoint_returns_500_on_invalid_json(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/save', data=b'{', headers={'Content-Type': 'application/json', 'X-FAPAI-Control-Token': 'test-operator'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_INVALID_JSON')

    def test_collection_seed_batch_alias_returns_json_error_on_failure(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/collection/seeds/batch', data=json.dumps({'items': [{'id': '1'}]}).encode('utf-8'), headers={'Content-Type': 'application/json', 'X-FAPAI-Control-Token': 'test-operator'}, method='POST')
        with mock.patch.object(server_module, 'handle_seed_batch_submission', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_SEED_BATCH_FAILED')
        self.assertRegex(body['error']['details']['error_id'], r'^[a-f0-9]{16}$')

    def test_save_legacy_endpoint_returns_json_error_on_failure(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/save', data=json.dumps({'items': [{'id': '1'}]}).encode('utf-8'), headers={'Content-Type': 'application/json', 'X-FAPAI-Control-Token': 'test-operator'}, method='POST')
        with mock.patch.object(server_module, 'handle_seed_batch_submission', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_SEED_BATCH_FAILED')
        self.assertRegex(body['error']['details']['error_id'], r'^[a-f0-9]{16}$')

    def test_manual_review_receipts_crud_endpoint(self):
        (status, payload) = self._get_json('/api/avm/manual_review_receipts')
        self.assertEqual(status, 200)
        self.assertEqual(payload['receipt_count'], 0)
        self.assertEqual(payload['manual_review_control_plane_storage']['state_source'], 'json_fallback')
        self.assertEqual(payload['manual_review_control_plane_backup']['backup_state'], 'runtime_json')
        (status, backend_status) = self._get_json('/api/avm/manual_review_control_plane_status')
        self.assertEqual(status, 200)
        self.assertEqual(backend_status['manual_review_control_plane_storage']['state_source'], 'json_fallback')
        self.assertEqual(backend_status['manual_review_control_plane_backup']['backup_state'], 'runtime_json')
        self.assertEqual(backend_status['manual_review_control_plane_backup_repairs_summary']['repair_count'], 0)
        self.assertEqual(backend_status['manual_review_control_plane_integrity']['integrity_status'], 'healthy_json_runtime')
        self.assertFalse(backend_status['manual_review_control_plane_integrity']['attention_required'])
        self.assertEqual(backend_status['manual_review_control_plane_stability']['stability_status'], 'stable_json_runtime')
        self.assertFalse(backend_status['manual_review_control_plane_stability']['attention_required'])
        self.assertEqual(backend_status['manual_review_control_plane_guidance']['guidance_status'], 'no_action_required')
        self.assertFalse(backend_status['manual_review_control_plane_guidance']['requires_operator_action'])
        self.assertIn('manual_review_receipt_jobs_summary', backend_status)
        self.assertIn('manual_review_receipt_operations_summary', backend_status)
        (status, repairs_payload) = self._get_json('/api/avm/manual_review_control_plane_backup_repairs')
        self.assertEqual(status, 200)
        self.assertEqual(repairs_payload['repair_count'], 0)
        self.assertEqual(repairs_payload['repairs'], [])
        self.assertEqual(repairs_payload['manual_review_control_plane_backup_repairs_summary']['repair_count'], 0)
        (status, integrity_history) = self._get_json('/api/avm/manual_review_control_plane_integrity_history')
        self.assertEqual(status, 200)
        self.assertEqual(integrity_history['transition_count'], 1)
        self.assertEqual(integrity_history['history'][0]['integrity_status'], 'healthy_json_runtime')
        self.assertEqual(integrity_history['manual_review_control_plane_integrity_history_summary']['last_integrity_status'], 'healthy_json_runtime')
        with mock.patch.object(server_module, 'run_recent_enrich_maintenance', return_value={'generated_at': 'x', 'manual_review_reentry_application_summary': {'reentry_applied': False}}) as mocked_maintenance:
            (status, payload) = self._post_json('/api/avm/manual_review_receipts', {'action': 'manual_location_review', 'ready_signal': 'location_artifacts_complete', 'status': 'ready_for_reentry', 'payload': {'full_address': 'A'}, 'mode': 'async'})
        self.assertEqual(status, 200)
        self.assertEqual(payload['operation'], 'created')
        self.assertEqual(payload['execution_mode'], 'async')
        self.assertTrue(payload['maintenance_triggered'])
        self.assertEqual(payload['maintenance_job_status'], 'queued')
        self.assertIn('maintenance_job_id', payload)
        self.assertEqual(payload['manual_review_control_plane_storage']['state_source'], 'json_fallback')
        self.assertEqual(payload['manual_review_control_plane_backup']['backup_state'], 'runtime_json')
        job_payload = self._wait_for_job(payload['maintenance_job_id'])
        self.assertEqual(job_payload['job']['status'], 'completed')
        mocked_maintenance.assert_called_once()
        (status, payload) = self._get_json('/api/avm/manual_review_receipts')
        self.assertEqual(status, 200)
        self.assertEqual(payload['receipt_count'], 1)
        self.assertEqual(payload['receipts'][0]['action'], 'manual_location_review')
        (status, payload) = self._delete_json('/api/avm/manual_review_receipts', {'action': 'manual_location_review', 'ready_signal': 'location_artifacts_complete'})
        self.assertEqual(status, 200)
        self.assertTrue(payload['deleted'])
        self.assertEqual(payload['receipt_count'], 0)

    def test_manual_review_receipts_endpoint_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, 'list_manual_review_receipts', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/avm/manual_review_receipts')
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_MANUAL_REVIEW_RECEIPTS_READ_FAILED')
        self.assertRegex(body['error']['details']['error_id'], r'^[a-f0-9]{16}$')

__all__ = ["AVMHttpContractPart06"]
