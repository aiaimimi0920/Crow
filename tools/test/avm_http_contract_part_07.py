from __future__ import annotations

from src import manual_review_status
from tools.test.avm_http_contract_context import *  # noqa: F401,F403


class AVMHttpContractPart07:
    def test_analysis_manual_review_receipts_crud_alias_endpoint(self):
        (status, payload) = self._get_json('/api/analysis/manual_review_receipts')
        self.assertEqual(status, 200)
        self.assertEqual(payload['receipt_count'], 0)
        self.assertEqual(payload['manual_review_control_plane_storage']['state_source'], 'json_fallback')
        self.assertEqual(payload['manual_review_control_plane_backup']['backup_state'], 'runtime_json')
        (status, backend_status) = self._get_json('/api/analysis/manual_review_control_plane_status')
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
        (status, repairs_payload) = self._get_json('/api/analysis/manual_review_control_plane_backup_repairs')
        self.assertEqual(status, 200)
        self.assertEqual(repairs_payload['repair_count'], 0)
        self.assertEqual(repairs_payload['repairs'], [])
        self.assertEqual(repairs_payload['manual_review_control_plane_backup_repairs_summary']['repair_count'], 0)
        (status, integrity_history) = self._get_json('/api/analysis/manual_review_control_plane_integrity_history')
        self.assertEqual(status, 200)
        self.assertEqual(integrity_history['transition_count'], 1)
        self.assertEqual(integrity_history['history'][0]['integrity_status'], 'healthy_json_runtime')
        self.assertEqual(integrity_history['manual_review_control_plane_integrity_history_summary']['last_integrity_status'], 'healthy_json_runtime')
        with mock.patch.object(server_module, 'run_recent_enrich_maintenance', return_value={'generated_at': 'x', 'manual_review_reentry_application_summary': {'reentry_applied': False}}) as mocked_maintenance:
            (status, payload) = self._post_json('/api/analysis/manual_review_receipts', {'action': 'manual_location_review', 'ready_signal': 'location_artifacts_complete', 'status': 'ready_for_reentry', 'payload': {'full_address': 'A'}, 'mode': 'async'})
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
        (status, payload) = self._get_json('/api/analysis/manual_review_receipts')
        self.assertEqual(status, 200)
        self.assertEqual(payload['receipt_count'], 1)
        self.assertEqual(payload['receipts'][0]['action'], 'manual_location_review')
        (status, payload) = self._delete_json('/api/analysis/manual_review_receipts', {'action': 'manual_location_review', 'ready_signal': 'location_artifacts_complete'})
        self.assertEqual(status, 200)
        self.assertTrue(payload['deleted'])
        self.assertEqual(payload['receipt_count'], 0)

    def test_analysis_manual_review_receipts_endpoint_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, 'list_manual_review_receipts', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/analysis/manual_review_receipts')
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_MANUAL_REVIEW_RECEIPTS_READ_FAILED')
        self.assertRegex(body['error']['details']['error_id'], r'^[a-f0-9]{16}$')

    def test_manual_review_control_plane_status_records_integrity_once_per_request(self):
        original = manual_review_status.record_manual_review_control_plane_integrity
        calls = []

        def _spy(data_root, integrity):
            calls.append(dict(integrity))
            return original(data_root, integrity)
        with mock.patch.object(manual_review_status, 'record_manual_review_control_plane_integrity', side_effect=_spy):
            (status, payload) = self._get_json('/api/avm/manual_review_control_plane_status')
        self.assertEqual(status, 200)
        self.assertEqual(payload['manual_review_control_plane_integrity']['integrity_status'], 'healthy_json_runtime')
        self.assertEqual(len(calls), 1)

    def test_manual_review_control_plane_status_endpoint_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, '_manual_review_receipt_context', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/avm/manual_review_control_plane_status')
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_MANUAL_REVIEW_CONTROL_PLANE_STATUS_FAILED')
        self.assertRegex(body['error']['details']['error_id'], r'^[a-f0-9]{16}$')

    def test_manual_review_control_plane_backup_repairs_endpoint_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, 'load_manual_review_control_plane_backup_repairs', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/avm/manual_review_control_plane_backup_repairs')
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_MANUAL_REVIEW_CONTROL_PLANE_BACKUP_REPAIRS_FAILED')
        self.assertRegex(body['error']['details']['error_id'], r'^[a-f0-9]{16}$')

    def test_manual_review_control_plane_backup_repairs_endpoints_default_invalid_limit_query_params(self):
        mocked_repairs = [{'repair_status': 'scheduled'}, {'repair_status': 'completed'}]
        with mock.patch.object(server_module, 'load_manual_review_control_plane_backup_repairs', return_value=mocked_repairs):
            for path in ('/api/avm/manual_review_control_plane_backup_repairs?limit=bad', '/api/analysis/manual_review_control_plane_backup_repairs?limit=bad'):
                with self.subTest(path=path):
                    (status, payload) = self._get_json(path)
                    self.assertEqual(status, 200)
                    self.assertEqual(payload['repair_count'], 2)
                    self.assertEqual(payload['applied_filters']['limit'], 50)

    def test_manual_review_control_plane_backup_repairs_endpoints_clamp_negative_limit(self):
        mocked_repairs = [{'repair_status': 'scheduled'}, {'repair_status': 'completed'}]
        with mock.patch.object(server_module, 'load_manual_review_control_plane_backup_repairs', return_value=mocked_repairs):
            for path in ('/api/avm/manual_review_control_plane_backup_repairs?limit=-1', '/api/analysis/manual_review_control_plane_backup_repairs?limit=-1'):
                with self.subTest(path=path):
                    (status, payload) = self._get_json(path)
                    self.assertEqual(status, 200)
                    self.assertEqual(payload['repair_count'], 0)
                    self.assertEqual(payload['repairs'], [])
                    self.assertEqual(payload['applied_filters']['limit'], 0)

    def test_manual_review_control_plane_integrity_history_endpoint_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, 'load_manual_review_control_plane_integrity_history', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/avm/manual_review_control_plane_integrity_history')
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_MANUAL_REVIEW_CONTROL_PLANE_INTEGRITY_HISTORY_FAILED')
        self.assertRegex(body['error']['details']['error_id'], r'^[a-f0-9]{16}$')

    def test_manual_review_control_plane_integrity_history_endpoints_default_invalid_limit_query_params(self):
        mocked_history = [{'integrity_status': 'healthy_json_runtime'}, {'integrity_status': 'backup_repair_scheduled'}]
        with mock.patch.object(server_module, 'load_manual_review_control_plane_integrity_history', return_value=mocked_history):
            for path in ('/api/avm/manual_review_control_plane_integrity_history?limit=bad', '/api/analysis/manual_review_control_plane_integrity_history?limit=bad'):
                with self.subTest(path=path):
                    (status, payload) = self._get_json(path)
                    self.assertEqual(status, 200)
                    self.assertEqual(payload['transition_count'], 2)
                    self.assertEqual(payload['applied_filters']['limit'], 50)

    def test_manual_review_control_plane_integrity_history_endpoints_clamp_negative_limit(self):
        mocked_history = [{'integrity_status': 'healthy_json_runtime'}, {'integrity_status': 'backup_repair_scheduled'}]
        with mock.patch.object(server_module, 'load_manual_review_control_plane_integrity_history', return_value=mocked_history):
            for path in ('/api/avm/manual_review_control_plane_integrity_history?limit=-1', '/api/analysis/manual_review_control_plane_integrity_history?limit=-1'):
                with self.subTest(path=path):
                    (status, payload) = self._get_json(path)
                    self.assertEqual(status, 200)
                    self.assertEqual(payload['transition_count'], 0)
                    self.assertEqual(payload['history'], [])
                    self.assertEqual(payload['applied_filters']['limit'], 0)

    def test_analysis_manual_review_control_plane_status_records_integrity_once_per_request(self):
        original = manual_review_status.record_manual_review_control_plane_integrity
        calls = []

        def _spy(data_root, integrity):
            calls.append(dict(integrity))
            return original(data_root, integrity)
        with mock.patch.object(manual_review_status, 'record_manual_review_control_plane_integrity', side_effect=_spy):
            (status, payload) = self._get_json('/api/analysis/manual_review_control_plane_status')
        self.assertEqual(status, 200)
        self.assertEqual(payload['manual_review_control_plane_integrity']['integrity_status'], 'healthy_json_runtime')
        self.assertEqual(len(calls), 1)

    def test_analysis_manual_review_control_plane_status_endpoint_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, '_manual_review_receipt_context', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/analysis/manual_review_control_plane_status')
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_MANUAL_REVIEW_CONTROL_PLANE_STATUS_FAILED')
        self.assertRegex(body['error']['details']['error_id'], r'^[a-f0-9]{16}$')

    def test_analysis_manual_review_control_plane_backup_repairs_endpoint_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, 'load_manual_review_control_plane_backup_repairs', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/analysis/manual_review_control_plane_backup_repairs')
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_MANUAL_REVIEW_CONTROL_PLANE_BACKUP_REPAIRS_FAILED')
        self.assertRegex(body['error']['details']['error_id'], r'^[a-f0-9]{16}$')

    def test_analysis_manual_review_control_plane_integrity_history_endpoint_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, 'load_manual_review_control_plane_integrity_history', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/analysis/manual_review_control_plane_integrity_history')
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_MANUAL_REVIEW_CONTROL_PLANE_INTEGRITY_HISTORY_FAILED')
        self.assertRegex(body['error']['details']['error_id'], r'^[a-f0-9]{16}$')

    def test_manual_review_receipts_sync_mode_can_trigger_maintenance(self):
        fake_report = {'generated_at': 'x', 'manual_review_reentry_application_summary': {'reentry_applied': False}, 'operator_overview': {'handoff_lifecycle_state': 'receipt_ready_for_reentry'}}
        with mock.patch.object(server_module, 'run_recent_enrich_maintenance', return_value=fake_report) as mocked_maintenance:
            (status, payload) = self._post_collection_job('/api/avm/manual_review_receipts', {'action': 'manual_location_review', 'ready_signal': 'location_artifacts_complete', 'status': 'ready_for_reentry', 'payload': {'full_address': 'A'}, 'mode': 'sync'})
        self.assertEqual(status, 202)
        self.assertEqual(payload['execution_mode'], 'sync')
        self.assertTrue(payload['maintenance_triggered'])
        self.assertEqual(payload['maintenance_report']['generated_at'], 'x')
        mocked_maintenance.assert_called_once()

    def test_manual_review_receipts_sync_mode_returns_json_error_on_maintenance_failure(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/avm/manual_review_receipts', data=json.dumps({'action': 'manual_location_review', 'ready_signal': 'location_artifacts_complete', 'status': 'ready_for_reentry', 'payload': {'full_address': 'A'}, 'mode': 'sync'}).encode('utf-8'), headers={'Content-Type': 'application/json', 'X-FAPAI-Control-Token': 'test-operator'}, method='POST')
        with mock.patch.object(server_module, 'run_recent_enrich_maintenance', side_effect=RuntimeError('boom')):
            with urllib.request.urlopen(req) as response:
                self._assert_collection_job_failed(response.status, json.load(response), 'AVM_MANUAL_REVIEW_RECEIPT_MAINTENANCE_FAILED')

    def test_analysis_manual_review_receipts_sync_mode_can_trigger_maintenance(self):
        fake_report = {'generated_at': 'x', 'manual_review_reentry_application_summary': {'reentry_applied': False}, 'operator_overview': {'handoff_lifecycle_state': 'receipt_ready_for_reentry'}}
        with mock.patch.object(server_module, 'run_recent_enrich_maintenance', return_value=fake_report) as mocked_maintenance:
            (status, payload) = self._post_collection_job('/api/analysis/manual_review_receipts', {'action': 'manual_location_review', 'ready_signal': 'location_artifacts_complete', 'status': 'ready_for_reentry', 'payload': {'full_address': 'A'}, 'mode': 'sync'})
        self.assertEqual(status, 202)
        self.assertEqual(payload['execution_mode'], 'sync')
        self.assertTrue(payload['maintenance_triggered'])
        self.assertEqual(payload['maintenance_report']['generated_at'], 'x')
        mocked_maintenance.assert_called_once()

    def test_analysis_manual_review_receipts_sync_mode_returns_json_error_on_maintenance_failure(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/analysis/manual_review_receipts', data=json.dumps({'action': 'manual_location_review', 'ready_signal': 'location_artifacts_complete', 'status': 'ready_for_reentry', 'payload': {'full_address': 'A'}, 'mode': 'sync'}).encode('utf-8'), headers={'Content-Type': 'application/json', 'X-FAPAI-Control-Token': 'test-operator'}, method='POST')
        with mock.patch.object(server_module, 'run_recent_enrich_maintenance', side_effect=RuntimeError('boom')):
            with urllib.request.urlopen(req) as response:
                self._assert_collection_job_failed(response.status, json.load(response), 'AVM_MANUAL_REVIEW_RECEIPT_MAINTENANCE_FAILED')

    def test_manual_review_receipt_jobs_endpoint_lists_async_jobs(self):
        with mock.patch.object(server_module, 'run_recent_enrich_maintenance', return_value={'generated_at': 'x'}) as mocked_maintenance:
            (status, payload) = self._post_json('/api/avm/manual_review_receipts', {'action': 'manual_status_review', 'ready_signal': 'status_reconciled', 'status': 'ready_for_reentry', 'payload': {'status_notes': 'ok'}, 'mode': 'async'})
        self.assertEqual(status, 200)
        job_id = payload['maintenance_job_id']
        completed = self._wait_for_job(job_id)
        self.assertEqual(completed['job']['status'], 'completed')
        (status, jobs_payload) = self._get_json('/api/avm/manual_review_receipt_jobs')
        self.assertEqual(status, 200)
        self.assertGreaterEqual(jobs_payload['job_count'], 1)
        self.assertTrue(any((job['job_id'] == job_id for job in jobs_payload['jobs'])))
        mocked_maintenance.assert_called_once()

    def test_manual_review_receipt_jobs_endpoint_returns_null_job_for_unknown_job_id(self):
        snapshot = {'jobs': [], 'running_job_id': None}
        with mock.patch.object(server_module, '_manual_review_receipt_jobs_snapshot', return_value=snapshot):
            (status, payload) = self._get_json('/api/avm/manual_review_receipt_jobs?job_id=missing-job')
        self.assertEqual(status, 200)
        self.assertEqual(payload['job_count'], 0)
        self.assertIsNone(payload['job'])
        self.assertEqual(payload['queued_jobs'], [])

    def test_manual_review_receipt_jobs_endpoint_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, '_manual_review_receipt_jobs_snapshot', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/avm/manual_review_receipt_jobs')
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_MANUAL_REVIEW_RECEIPT_JOBS_READ_FAILED')
        self.assertRegex(body['error']['details']['error_id'], r'^[a-f0-9]{16}$')

    def test_analysis_manual_review_receipt_jobs_alias_endpoint_lists_async_jobs(self):
        with mock.patch.object(server_module, 'run_recent_enrich_maintenance', return_value={'generated_at': 'x'}) as mocked_maintenance:
            (status, payload) = self._post_json('/api/analysis/manual_review_receipts', {'action': 'manual_status_review', 'ready_signal': 'status_reconciled', 'status': 'ready_for_reentry', 'payload': {'status_notes': 'ok'}, 'mode': 'async'})
        self.assertEqual(status, 200)
        job_id = payload['maintenance_job_id']
        completed = self._wait_for_job(job_id)
        self.assertEqual(completed['job']['status'], 'completed')
        (status, jobs_payload) = self._get_json('/api/analysis/manual_review_receipt_jobs')
        self.assertEqual(status, 200)
        self.assertGreaterEqual(jobs_payload['job_count'], 1)
        self.assertTrue(any((job['job_id'] == job_id for job in jobs_payload['jobs'])))
        mocked_maintenance.assert_called_once()

    def test_analysis_manual_review_receipt_jobs_alias_returns_null_job_for_unknown_job_id(self):
        snapshot = {'jobs': [], 'running_job_id': None}
        with mock.patch.object(server_module, '_manual_review_receipt_jobs_snapshot', return_value=snapshot):
            (status, payload) = self._get_json('/api/analysis/manual_review_receipt_jobs?job_id=missing-job')
        self.assertEqual(status, 200)
        self.assertEqual(payload['job_count'], 0)
        self.assertIsNone(payload['job'])
        self.assertEqual(payload['queued_jobs'], [])

    def test_analysis_manual_review_receipt_jobs_alias_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, '_manual_review_receipt_jobs_snapshot', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/analysis/manual_review_receipt_jobs')
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_MANUAL_REVIEW_RECEIPT_JOBS_READ_FAILED')
        self.assertRegex(body['error']['details']['error_id'], r'^[a-f0-9]{16}$')

    def test_manual_review_receipt_operations_endpoint_lists_and_filters_history(self):
        with mock.patch.object(server_module, 'run_recent_enrich_maintenance', return_value={'generated_at': 'x'}):
            (status, created) = self._post_json('/api/avm/manual_review_receipts', {'action': 'manual_location_review', 'ready_signal': 'location_artifacts_complete', 'status': 'ready_for_reentry', 'payload': {'full_address': 'A'}, 'mode': 'async'})
            self.assertEqual(status, 200)
            self._wait_for_job(created['maintenance_job_id'])
            (status, updated) = self._post_collection_job('/api/avm/manual_review_receipts', {'action': 'manual_location_review', 'ready_signal': 'location_artifacts_complete', 'status': 'ready_for_reentry', 'payload': {'full_address': 'B'}, 'mode': 'sync'})
            self.assertEqual(status, 202)
            (status, deleted) = self._delete_json('/api/avm/manual_review_receipts', {'action': 'manual_location_review', 'ready_signal': 'location_artifacts_complete'})
            self.assertEqual(status, 200)
        (status, payload) = self._get_json('/api/avm/manual_review_receipt_operations')
        self.assertEqual(status, 200)
        self.assertGreaterEqual(payload['operation_count'], 3)
        self.assertEqual(payload['operations'][0]['operation'], 'deleted')
        self.assertEqual(payload['operations'][1]['operation'], 'updated')
        self.assertEqual(payload['operations'][2]['operation'], 'created')
        self.assertEqual(payload['manual_review_control_plane_storage']['state_source'], 'json_fallback')
        self.assertEqual(payload['manual_review_control_plane_backup']['backup_state'], 'runtime_json')
        (status, filtered) = self._get_json('/api/avm/manual_review_receipt_operations?action=manual_location_review&ready_signal=location_artifacts_complete&limit=2')
        self.assertEqual(status, 200)
        self.assertEqual(filtered['operation_count'], 2)
        self.assertEqual(filtered['operations'][0]['ready_signal'], 'location_artifacts_complete')

    def test_manual_review_receipt_operations_endpoint_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, 'load_manual_review_receipt_operations', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/avm/manual_review_receipt_operations')
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_MANUAL_REVIEW_RECEIPT_OPERATIONS_READ_FAILED')
        self.assertRegex(body['error']['details']['error_id'], r'^[a-f0-9]{16}$')

    def test_manual_review_receipt_operations_endpoints_default_invalid_limit_query_params(self):
        mocked_operations = [{'operation': 'created', 'ready_signal': 'location_artifacts_complete'}, {'operation': 'updated', 'ready_signal': 'location_artifacts_complete'}]
        with mock.patch.object(server_module, 'load_manual_review_receipt_operations', return_value=mocked_operations), mock.patch.object(server_module, 'filter_manual_review_receipt_operations', return_value=mocked_operations) as mocked_filter:
            for path in ('/api/avm/manual_review_receipt_operations?limit=bad', '/api/analysis/manual_review_receipt_operations?limit=bad'):
                with self.subTest(path=path):
                    (status, payload) = self._get_json(path)
                    self.assertEqual(status, 200)
                    self.assertEqual(payload['operation_count'], 2)
                    self.assertEqual(payload['applied_filters']['limit'], 50)
        self.assertEqual(mocked_filter.call_args_list[0].kwargs['limit'], 50)
        self.assertEqual(mocked_filter.call_args_list[1].kwargs['limit'], 50)

    def test_manual_review_receipt_operations_endpoints_clamp_negative_limit(self):
        mocked_operations = [{'operation': 'created', 'ready_signal': 'location_artifacts_complete'}, {'operation': 'updated', 'ready_signal': 'location_artifacts_complete'}]
        with mock.patch.object(server_module, 'load_manual_review_receipt_operations', return_value=mocked_operations), mock.patch.object(server_module, 'filter_manual_review_receipt_operations', side_effect=lambda operations, **kwargs: [] if kwargs.get('limit') == 0 else mocked_operations) as mocked_filter:
            for path in ('/api/avm/manual_review_receipt_operations?limit=-1', '/api/analysis/manual_review_receipt_operations?limit=-1'):
                with self.subTest(path=path):
                    (status, payload) = self._get_json(path)
                    self.assertEqual(status, 200)
                    self.assertEqual(payload['operation_count'], 0)
                    self.assertEqual(payload['operations'], [])
                    self.assertEqual(payload['applied_filters']['limit'], 0)
        self.assertEqual(mocked_filter.call_args_list[0].kwargs['limit'], 0)
        self.assertEqual(mocked_filter.call_args_list[1].kwargs['limit'], 0)

    def test_analysis_manual_review_receipt_operations_alias_endpoint_lists_and_filters_history(self):
        with mock.patch.object(server_module, 'run_recent_enrich_maintenance', return_value={'generated_at': 'x'}):
            (status, created) = self._post_json('/api/analysis/manual_review_receipts', {'action': 'manual_location_review', 'ready_signal': 'location_artifacts_complete', 'status': 'ready_for_reentry', 'payload': {'full_address': 'A'}, 'mode': 'async'})
            self.assertEqual(status, 200)
            self._wait_for_job(created['maintenance_job_id'])
            (status, updated) = self._post_collection_job('/api/analysis/manual_review_receipts', {'action': 'manual_location_review', 'ready_signal': 'location_artifacts_complete', 'status': 'ready_for_reentry', 'payload': {'full_address': 'B'}, 'mode': 'sync'})
            self.assertEqual(status, 202)
            (status, deleted) = self._delete_json('/api/analysis/manual_review_receipts', {'action': 'manual_location_review', 'ready_signal': 'location_artifacts_complete'})
            self.assertEqual(status, 200)
        (status, payload) = self._get_json('/api/analysis/manual_review_receipt_operations')
        self.assertEqual(status, 200)
        self.assertGreaterEqual(payload['operation_count'], 3)
        self.assertEqual(payload['operations'][0]['operation'], 'deleted')
        self.assertEqual(payload['operations'][1]['operation'], 'updated')
        self.assertEqual(payload['operations'][2]['operation'], 'created')
        self.assertEqual(payload['manual_review_control_plane_storage']['state_source'], 'json_fallback')
        self.assertEqual(payload['manual_review_control_plane_backup']['backup_state'], 'runtime_json')
        (status, filtered) = self._get_json('/api/analysis/manual_review_receipt_operations?action=manual_location_review&ready_signal=location_artifacts_complete&limit=2')
        self.assertEqual(status, 200)
        self.assertEqual(filtered['operation_count'], 2)
        self.assertEqual(filtered['operations'][0]['ready_signal'], 'location_artifacts_complete')

    def test_analysis_manual_review_receipt_operations_alias_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, 'load_manual_review_receipt_operations', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/analysis/manual_review_receipt_operations')
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_MANUAL_REVIEW_RECEIPT_OPERATIONS_READ_FAILED')
        self.assertRegex(body['error']['details']['error_id'], r'^[a-f0-9]{16}$')

    def test_manual_review_receipts_reject_missing_action(self):
        for path in ('/api/avm/manual_review_receipts', '/api/analysis/manual_review_receipts'):
            with self.subTest(path=path):
                req = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', data=json.dumps({'ready_signal': 'location_artifacts_complete', 'status': 'ready_for_reentry', 'payload': {'full_address': 'A'}}).encode('utf-8'), headers={'Content-Type': 'application/json', 'X-FAPAI-Control-Token': 'test-operator'}, method='POST')
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req)
                self.assertEqual(ctx.exception.code, 400)
                body = json.loads(ctx.exception.read().decode('utf-8'))
                self.assertEqual(body['error']['code'], 'AVM_INVALID_RECEIPT_ACTION')

    def test_manual_review_receipts_reject_missing_ready_signal(self):
        for path in ('/api/avm/manual_review_receipts', '/api/analysis/manual_review_receipts'):
            with self.subTest(path=path):
                req = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', data=json.dumps({'action': 'manual_location_review', 'status': 'ready_for_reentry', 'payload': {'full_address': 'A'}}).encode('utf-8'), headers={'Content-Type': 'application/json', 'X-FAPAI-Control-Token': 'test-operator'}, method='POST')
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req)
                self.assertEqual(ctx.exception.code, 400)
                body = json.loads(ctx.exception.read().decode('utf-8'))
                self.assertEqual(body['error']['code'], 'AVM_INVALID_RECEIPT_SIGNAL')

    def test_manual_review_receipts_reject_missing_status(self):
        for path in ('/api/avm/manual_review_receipts', '/api/analysis/manual_review_receipts'):
            with self.subTest(path=path):
                req = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', data=json.dumps({'action': 'manual_location_review', 'ready_signal': 'location_artifacts_complete', 'payload': {'full_address': 'A'}}).encode('utf-8'), headers={'Content-Type': 'application/json', 'X-FAPAI-Control-Token': 'test-operator'}, method='POST')
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req)
                self.assertEqual(ctx.exception.code, 400)
                body = json.loads(ctx.exception.read().decode('utf-8'))
                self.assertEqual(body['error']['code'], 'AVM_INVALID_RECEIPT_STATUS')

    def test_manual_review_receipts_reject_invalid_payload_shape(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/avm/manual_review_receipts', data=json.dumps({'action': 'manual_location_review', 'ready_signal': 'location_artifacts_complete', 'status': 'ready_for_reentry', 'payload': 'not-an-object'}).encode('utf-8'), headers={'Content-Type': 'application/json', 'X-FAPAI-Control-Token': 'test-operator'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_INVALID_RECEIPT_PAYLOAD')

    def test_analysis_manual_review_receipts_reject_invalid_payload_shape(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/analysis/manual_review_receipts', data=json.dumps({'action': 'manual_location_review', 'ready_signal': 'location_artifacts_complete', 'status': 'ready_for_reentry', 'payload': 'not-an-object'}).encode('utf-8'), headers={'Content-Type': 'application/json', 'X-FAPAI-Control-Token': 'test-operator'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_INVALID_RECEIPT_PAYLOAD')

    def test_manual_review_receipts_reject_invalid_mode(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/avm/manual_review_receipts', data=json.dumps({'action': 'manual_location_review', 'ready_signal': 'location_artifacts_complete', 'status': 'ready_for_reentry', 'payload': {'full_address': 'A'}, 'mode': 'later'}).encode('utf-8'), headers={'Content-Type': 'application/json', 'X-FAPAI-Control-Token': 'test-operator'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_INVALID_RECEIPT_MODE')

    def test_manual_review_receipts_endpoint_returns_json_error_on_upsert_failure(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/avm/manual_review_receipts', data=json.dumps({'action': 'manual_location_review', 'ready_signal': 'location_artifacts_complete', 'status': 'ready_for_reentry', 'payload': {'full_address': 'A'}, 'mode': 'sync'}).encode('utf-8'), headers={'Content-Type': 'application/json', 'X-FAPAI-Control-Token': 'test-operator'}, method='POST')
        with mock.patch.object(server_module, 'upsert_manual_review_receipt', side_effect=RuntimeError('boom')):
            with urllib.request.urlopen(req) as response:
                self._assert_collection_job_failed(response.status, json.load(response), 'AVM_MANUAL_REVIEW_RECEIPT_UPSERT_FAILED')

    def test_manual_review_receipts_endpoint_returns_json_error_on_async_enqueue_failure(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/avm/manual_review_receipts', data=json.dumps({'action': 'manual_location_review', 'ready_signal': 'location_artifacts_complete', 'status': 'ready_for_reentry', 'payload': {'full_address': 'A'}, 'mode': 'async'}).encode('utf-8'), headers={'Content-Type': 'application/json', 'X-FAPAI-Control-Token': 'test-operator'}, method='POST')
        from src.collection_jobs import JobQueueFull
        with mock.patch('src.collection_jobs.CollectionJobManager.submit', side_effect=JobQueueFull('full')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 503)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'COLLECTION_JOB_QUEUE_FULL')

__all__ = ["AVMHttpContractPart07"]
