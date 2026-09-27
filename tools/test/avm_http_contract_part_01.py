from __future__ import annotations

from tools.test.avm_http_contract_context import *  # noqa: F401,F403


class AVMHttpContractPart01:
    def test_repo_owned_python_files_compile(self):
        files = self._repo_owned_python_files()
        self.assertGreater(len(files), 0)
        for index, path in enumerate(files):
            with self.subTest(path=str(path)):
                py_compile.compile(str(path), cfile=str(Path(self.tmp.name) / f'compile-{index}.pyc'), doraise=True)

    def test_repo_owned_python_test_inventory_is_covered_by_primary_test_dirs(self):
        self.assertEqual(self._repo_owned_python_test_files(), self._primary_repo_test_files())

    def test_unknown_api_get_returns_json_404_error(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/does-not-exist')
        self.assertEqual(ctx.exception.code, 404)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_ENDPOINT_NOT_FOUND')
        self.assertEqual(body['error']['details']['path'], '/api/does-not-exist')

    def test_unknown_api_post_returns_json_404_error(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/does-not-exist', data=b'', headers={'Content-Type': 'application/json', 'X-FAPAI-Control-Token': 'test-operator'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 404)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_ENDPOINT_NOT_FOUND')
        self.assertEqual(body['error']['details']['path'], '/api/does-not-exist')

    def test_unknown_api_delete_returns_json_404_error(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/does-not-exist', data=b'', headers={'Content-Type': 'application/json', 'X-FAPAI-Control-Token': 'test-operator'}, method='DELETE')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 404)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_ENDPOINT_NOT_FOUND')
        self.assertEqual(body['error']['details']['path'], '/api/does-not-exist')

    def test_health_endpoint(self):
        self._get_json('/api/avm/predict?id=3001')
        (status, payload) = self._get_json('/api/avm/health')
        self.assertEqual(status, 200)
        self.assertEqual(payload['status'], 'ok')
        self.assertEqual(payload['service'], 'avm')
        self.assertGreaterEqual(payload['dataset_size'], 2)
        self.assertIn('feature_cache_hit_rate', payload)
        self.assertIn('strategy_counts', payload)
        self.assertIn('avg_predict_time_ms', payload)
        self.assertIn('db_mode', payload)
        self.assertIn('db_total_ids', payload)
        self.assertIn('db_pending_ids', payload)
        self.assertIn('collection_stage', payload)
        self.assertIn('analysis_blockers', payload['collection_stage'])
        self.assertIn('recommended_actions', payload['collection_stage'])
        self.assertIn('operator_action_summary', payload['collection_stage'])
        self.assertIn('recoverability_summary', payload['collection_stage'])
        self.assertIn('scheduler_feedback_summary', payload['collection_stage'])
        self.assertIn('manual_review_backlog_summary', payload['collection_stage'])
        self.assertIn('operator_overview', payload['collection_stage'])
        self.assertIn('calibration_guidance', payload)
        self.assertIn('coordinate_strategy_watchlist', payload)
        if payload['db_mode']:
            self.assertIn('stage_transition_recent', payload['data_supply_recent_24h'])

    def test_health_endpoint_returns_json_error_on_health_snapshot_failure(self):
        with mock.patch.object(server_module.AVM_SERVICE, 'health_snapshot', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/avm/health')
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_HEALTH_FAILED')
        self.assertRegex(body['error']['details']['error_id'], r'^[a-f0-9]{16}$')

    def test_health_diagnostics_surfaces_calibration_guidance_and_coordinate_watchlist(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'calibration_targets.json'), 'w', encoding='utf-8') as f:
            json.dump({'risk_factor_targets': [{'target_type': 'risk_flag', 'name': 'is_occupied', 'suggested_next_factor': 0.5}], 'global_risk_targets': [{'target_type': 'global_risk', 'name': 'risk_discount_factor', 'suggested_next_value': 1.05}], 'temporal_targets': [{'target_type': 'temporal', 'name': 'time_decay', 'suggested_next_value': 0.72}], 'strategy_targets': [], 'config_patch': {'weighting': {'time_decay': 0.72}, 'risk_discount_factor': 1.05, 'risk_factor_overrides': {'is_occupied': 0.5}}, 'top_calibration_target': {'target_type': 'temporal', 'name': 'time_decay'}, 'top_calibration_target_hint': {'status': 'tune_temporal_decay', 'target_type': 'temporal', 'target_name': 'time_decay', 'playbook_id': 'tune-temporal-decay', 'runbook_refs': ['tools/evaluate_avm.py'], 'recommended_actions': ['adjust_weighting_time_decay'], 'suggested_commands': ['python tools/evaluate_avm.py'], 'suggested_bundle_commands': ['python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal'], 'recommended_bundle': {'bundle_id': 'temporal-global-risk', 'target_types': ['global_risk', 'temporal'], 'target_names': None}}, 'guidance': {'status': 'fix_coordinate_quality', 'priority': 'high', 'recommended_actions': ['review_coordinate_strategy_cohorts'], 'top_reason': 'district_centroid'}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump({'evaluation': {'top_coordinate_strategy_group': 'district_centroid', 'coordinate_strategy_watchlist': ['district_centroid']}}, f, ensure_ascii=False)
        (status, payload) = self._get_json('/api/avm/health')
        self.assertEqual(status, 200)
        self.assertEqual(payload['service'], 'avm')
        self.assertEqual(payload['calibration_guidance']['status'], 'fix_coordinate_quality')
        self.assertEqual(payload['top_calibration_target']['name'], 'time_decay')
        self.assertEqual(payload['top_calibration_target_hint']['target_name'], 'time_decay')
        self.assertEqual(payload['top_calibration_target_hint']['playbook_id'], 'tune-temporal-decay')
        self.assertIn('tools/evaluate_avm.py', payload['top_calibration_target_hint']['runbook_refs'])
        self.assertIn('python tools/evaluate_avm.py', payload['top_calibration_target_hint']['suggested_commands'])
        self.assertIn('python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal', payload['top_calibration_target_hint']['suggested_bundle_commands'])
        self.assertTrue(payload['calibration_patch_preview']['patch_ready'])
        self.assertEqual(payload['calibration_patch_preview']['changed_paths']['weighting.time_decay']['after'], 0.72)
        self.assertEqual(payload['calibration_patch_preview']['rollback_patch']['weighting']['time_decay'], 0.85)
        self.assertEqual(payload['calibration_target_counts']['global_risk'], 1)
        self.assertEqual(payload['top_calibration_patch_preview']['applied_filter'], {'target_type': 'temporal', 'target_name': 'time_decay'})
        self.assertEqual(payload['top_calibration_patch_preview']['changed_keys'], ['weighting.time_decay'])
        self.assertEqual(payload['recommended_bundle_patch_preview']['bundle_id'], 'temporal-global-risk')
        self.assertEqual(payload['recommended_bundle_patch_preview']['applied_filter'], {'target_types': ['global_risk', 'temporal'], 'target_names': None})
        self.assertEqual(payload['recommended_bundle_patch_preview']['changed_keys'], ['risk_discount_factor', 'weighting.time_decay'])
        self.assertEqual(payload['recommended_bundle_preview_command'], 'python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal')
        self.assertEqual(payload['recommended_bundle_write_command'], 'python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write')
        self.assertEqual(payload['recommended_bundle_verify_command'], 'python tools/evaluate_avm.py')
        self.assertEqual(payload['recommended_bundle_gate_command'], 'python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report')
        self.assertEqual(payload['recommended_bundle_risk_level'], 'medium')
        self.assertIn('multiple_changed_keys', payload['recommended_bundle_risk_reasons'])
        self.assertEqual(payload['recommended_bundle_next_action'], 'preview_only_first')
        self.assertIn('medium_risk_bundle', payload['recommended_bundle_next_action_reasons'])
        self.assertEqual(payload['recommended_bundle_next_action_command'], 'python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal')
        self.assertEqual(payload['recommended_bundle_next_action_command_kind'], 'preview')
        self.assertEqual(payload['recommended_bundle_follow_up_command'], 'python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write')
        self.assertEqual(payload['recommended_bundle_follow_up_command_kind'], 'write')
        command_chain = payload['recommended_bundle_command_chain']
        self.assertEqual([item['kind'] for item in command_chain], ['preview', 'write', 'verify', 'gate'])
        (preview_step, write_step, verify_step, gate_step) = command_chain
        self.assertEqual(preview_step['step_ready_action_command'], payload['recommended_bundle_preview_command'])
        self.assertEqual(preview_step['step_ready_follow_up_command'], payload['recommended_bundle_write_command'])
        self.assertEqual(preview_step['step_ready_stage_span'], 'write_then_evaluate')
        self.assertEqual(preview_step['artifact_state_reason'], 'config_not_written_yet')
        self.assertEqual(write_step['step_ready_action_command'], payload['recommended_bundle_write_command'])
        self.assertEqual(write_step['step_ready_follow_up_command'], payload['recommended_bundle_verify_command'])
        self.assertEqual(write_step['step_ready_stage_span'], 'write_then_evaluate')
        self.assertEqual(verify_step['step_ready_action_command'], payload['recommended_bundle_verify_command'])
        self.assertEqual(verify_step['step_ready_follow_up_command'], payload['recommended_bundle_gate_command'])
        self.assertEqual(verify_step['step_ready_stage_span'], 'evaluate_then_gate')
        self.assertEqual(verify_step['artifact_state_reason'], 'eval_not_rerun_yet')
        self.assertEqual(gate_step['step_ready_action_command'], payload['recommended_bundle_gate_command'])
        self.assertEqual(gate_step['step_ready_stage_span'], 'gate_only')
        self.assertEqual(gate_step['artifact_state_reason'], 'pre_bundle_gate_report')
        self.assertEqual(payload['coordinate_strategy_watchlist'], ['district_centroid'])
        self.assertEqual(payload['top_coordinate_strategy_group'], 'district_centroid')

    def test_status_endpoint_survives_health_snapshot_failure(self):
        with mock.patch.object(server_module.AVM_SERVICE, 'health_snapshot', side_effect=RuntimeError('boom')):
            status, payload = self._get_json('/api/status')
        self.assertEqual(status, 200)
        self.assertNotIn('avm', payload)
        self.assertIn('ai_finalized_count', payload)

    def test_health_diagnostics_stops_high_risk_bundle_chain_at_preview(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump({'radius_km': 3.0, 'weighting': {'distance_power': 2.0, 'time_decay': 0.85, 'community_boost': 1.3}, 'risk_discount_factor': 0.9, 'alert_threshold': 0.25, 'risk_factor_overrides': {'is_occupied': 0.8}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'calibration_targets.json'), 'w', encoding='utf-8') as f:
            json.dump({'temporal_targets': [{'target_type': 'temporal', 'name': 'time_decay', 'suggested_next_value': 0.72}], 'global_risk_targets': [{'target_type': 'global_risk', 'name': 'risk_discount_factor', 'suggested_next_value': 0.99}], 'risk_factor_targets': [{'target_type': 'risk_flag', 'name': 'is_occupied', 'suggested_next_factor': 0.5}], 'strategy_targets': [], 'config_patch': {'weighting': {'time_decay': 0.72}, 'risk_discount_factor': 0.99, 'risk_factor_overrides': {'is_occupied': 0.5}}, 'top_calibration_target': {'target_type': 'risk_flag', 'name': 'is_occupied'}, 'top_calibration_target_hint': {'status': 'tune_risk_factors', 'target_type': 'risk_flag', 'target_name': 'is_occupied', 'playbook_id': 'split-bundle-or-single-target-first', 'runbook_refs': ['tools/apply_avm_calibration_patch.py'], 'recommended_actions': ['split_bundle_or_single_target_first'], 'suggested_commands': ['python tools/apply_avm_calibration_patch.py --target-type risk_flag --target-name is_occupied'], 'suggested_bundle_commands': ['python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied', 'python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied --write', 'python tools/evaluate_avm.py', 'python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report'], 'recommended_bundle': {'bundle_id': 'temporal-global-risk-risk-flag', 'target_types': ['temporal', 'global_risk', 'risk_flag'], 'target_names': ['time_decay', 'risk_discount_factor', 'is_occupied']}}, 'guidance': {'status': 'tune_risk_factors', 'priority': 'high', 'recommended_actions': ['split_bundle_or_single_target_first'], 'top_reason': 'multi_flag_bundle'}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump({'evaluation': {}}, f, ensure_ascii=False)
        (status, payload) = self._get_json('/api/avm/health')
        self.assertEqual(status, 200)
        self.assertEqual(payload['recommended_bundle_risk_level'], 'high')
        self.assertIn('high_risk_bundle', payload['recommended_bundle_next_action_reasons'])
        self.assertEqual(payload['recommended_bundle_next_action'], 'split_bundle_or_single_target_first')
        self.assertEqual(payload['recommended_bundle_next_action_command'], 'python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied')
        self.assertEqual(payload['recommended_bundle_next_action_command_kind'], 'preview')
        self.assertEqual(payload['recommended_bundle_follow_up_command'], '')
        self.assertEqual(payload['recommended_bundle_follow_up_command_kind'], 'none')
        self.assertEqual(len(payload['recommended_bundle_command_chain']), 1)
        preview_step = payload['recommended_bundle_command_chain'][0]
        self.assertEqual(preview_step['kind'], 'preview')
        self.assertEqual(preview_step['step_ready_follow_up_command'], '')
        self.assertEqual(preview_step['step_ready_follow_up_expected_signal'], '')
        self.assertEqual(preview_step['step_ready_follow_up_success_criterion'], '')
        self.assertEqual(preview_step['step_ready_terminal_outcome'], 'ready_for_write_decision')
        self.assertEqual(preview_step['step_ready_stage_span'], 'preview_then_split')
        self.assertEqual(preview_step['step_ready_badge'], 'now-preview-then-split')
        self.assertEqual(preview_step['step_ready_group_id'], 'preview-and-split')
        self.assertEqual(preview_step['step_ready_display_order'], 0)

    def test_health_diagnostics_backfills_bundle_commands_from_recommended_bundle_when_suggestions_missing(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump({'radius_km': 3.0, 'weighting': {'distance_power': 2.0, 'time_decay': 0.85, 'community_boost': 1.3}, 'risk_discount_factor': 0.9, 'alert_threshold': 0.25, 'risk_factor_overrides': {}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'calibration_targets.json'), 'w', encoding='utf-8') as f:
            json.dump({'temporal_targets': [{'target_type': 'temporal', 'name': 'time_decay', 'suggested_next_value': 0.72}], 'global_risk_targets': [], 'risk_factor_targets': [], 'strategy_targets': [], 'config_patch': {'weighting': {'time_decay': 0.72}}, 'top_calibration_target': {'target_type': 'temporal', 'name': 'time_decay'}, 'top_calibration_target_hint': {'status': 'tune_temporal_decay', 'target_type': 'temporal', 'target_name': 'time_decay', 'playbook_id': 'tune-temporal-decay', 'runbook_refs': ['tools/evaluate_avm.py'], 'recommended_actions': ['adjust_weighting_time_decay'], 'suggested_commands': ['python tools/evaluate_avm.py'], 'recommended_bundle': {'bundle_id': 'temporal-only', 'target_types': ['temporal'], 'target_names': ['time_decay']}}, 'guidance': {'status': 'tune_temporal_decay', 'priority': 'medium', 'recommended_actions': ['adjust_weighting_time_decay'], 'top_reason': 'time_decay'}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump({'evaluation': {}}, f, ensure_ascii=False)
        (status, payload) = self._get_json('/api/avm/health')
        self.assertEqual(status, 200)
        self.assertEqual(payload['recommended_bundle_preview_command'], 'python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay')
        self.assertEqual(payload['recommended_bundle_write_command'], 'python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write')
        self.assertEqual(payload['recommended_bundle_verify_command'], 'python tools/evaluate_avm.py')
        self.assertEqual(payload['recommended_bundle_gate_command'], 'python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report')
        self.assertEqual(payload['recommended_bundle_next_action'], 'safe_to_write_then_verify')
        self.assertEqual(payload['recommended_bundle_next_action_command'], 'python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write')
        self.assertEqual(payload['recommended_bundle_follow_up_command'], 'python tools/evaluate_avm.py')
        self.assertEqual(payload['recommended_bundle_follow_up_command_kind'], 'verify')
        self.assertEqual([item['kind'] for item in payload['recommended_bundle_command_chain']], ['write', 'verify', 'gate'])

    def test_health_diagnostics_normalizes_malformed_calibration_target_lists(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'calibration_targets.json'), 'w', encoding='utf-8') as f:
            json.dump({'temporal_targets': {'target_type': 'temporal', 'name': 'time_decay', 'suggested_next_value': 0.72}, 'global_risk_targets': {}, 'risk_factor_targets': 'bad-shape', 'strategy_targets': None, 'top_calibration_target': {'target_type': 'temporal', 'name': 'time_decay'}, 'top_calibration_target_hint': {'status': 'tune_temporal_decay', 'target_type': 'temporal', 'target_name': 'time_decay', 'playbook_id': 'tune-temporal-decay', 'recommended_bundle': {'bundle_id': 'temporal-only', 'target_types': ['temporal'], 'target_names': ['time_decay']}}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump({'evaluation': {}}, f, ensure_ascii=False)
        (status, payload) = self._get_json('/api/avm/health')
        self.assertEqual(status, 200)
        self.assertEqual(payload['calibration_target_counts'], {'global_risk': 0, 'risk_factor': 0, 'temporal': 0, 'strategy': 0})
        self.assertEqual(payload['calibration_guidance']['status'], 'unavailable')
        self.assertEqual(payload['recommended_bundle_preview_command'], 'python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay')
        self.assertEqual(payload['recommended_bundle_write_command'], 'python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write')

    def test_health_diagnostics_tolerates_non_object_calibration_targets_file(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'calibration_targets.json'), 'w', encoding='utf-8') as f:
            json.dump([], f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump({'evaluation': {}}, f, ensure_ascii=False)
        (status, payload) = self._get_json('/api/avm/health')
        self.assertEqual(status, 200)
        self.assertEqual(payload['calibration_guidance']['status'], 'unavailable')
        self.assertEqual(payload['calibration_target_counts'], {'global_risk': 0, 'risk_factor': 0, 'temporal': 0, 'strategy': 0})
        self.assertEqual(payload['recommended_bundle_next_action'], 'no_action_required')

    def test_health_diagnostics_tolerates_non_object_config_file(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump([], f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump({'evaluation': {}}, f, ensure_ascii=False)
        (status, payload) = self._get_json('/api/avm/health')
        self.assertEqual(status, 200)
        self.assertEqual(payload['calibration_guidance']['status'], 'unavailable')
        self.assertEqual(payload['calibration_target_counts'], {'global_risk': 0, 'risk_factor': 0, 'temporal': 0, 'strategy': 0})
        self.assertEqual(payload['recommended_bundle_next_action'], 'no_action_required')

    def test_health_diagnostics_tolerates_malformed_config_file(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            f.write('{')
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump({'evaluation': {}}, f, ensure_ascii=False)
        (status, payload) = self._get_json('/api/avm/health')
        self.assertEqual(status, 200)
        self.assertEqual(payload['calibration_guidance']['status'], 'unavailable')
        self.assertEqual(payload['calibration_target_counts'], {'global_risk': 0, 'risk_factor': 0, 'temporal': 0, 'strategy': 0})
        self.assertEqual(payload['recommended_bundle_next_action'], 'no_action_required')

    def test_health_diagnostics_tolerates_invalid_object_config_file(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump({'radius_km': 3.0, 'weighting': [], 'risk_discount_factor': 0.9, 'alert_threshold': 0.25, 'risk_factor_overrides': {}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump({'evaluation': {}}, f, ensure_ascii=False)
        (status, payload) = self._get_json('/api/avm/health')
        self.assertEqual(status, 200)
        self.assertEqual(payload['calibration_guidance']['status'], 'unavailable')
        self.assertEqual(payload['calibration_target_counts'], {'global_risk': 0, 'risk_factor': 0, 'temporal': 0, 'strategy': 0})
        self.assertEqual(payload['recommended_bundle_next_action'], 'no_action_required')

    def test_health_diagnostics_uses_gate_embedded_calibration_targets_when_file_is_missing(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump({'radius_km': 3.0, 'weighting': {'distance_power': 2.0, 'time_decay': 0.85, 'community_boost': 1.3}, 'risk_discount_factor': 0.9, 'alert_threshold': 0.25, 'risk_factor_overrides': {}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump({'evaluation': {'coordinate_strategy_watchlist': [], 'calibration_targets': {'config_patch': {'weighting': {'time_decay': 0.72}}, 'temporal_targets': [{'target_type': 'temporal', 'name': 'time_decay', 'suggested_next_value': 0.72}], 'global_risk_targets': [], 'risk_factor_targets': [], 'strategy_targets': [], 'top_calibration_target': {'target_type': 'temporal', 'name': 'time_decay'}, 'top_calibration_target_hint': {'status': 'tune_temporal_decay', 'target_type': 'temporal', 'target_name': 'time_decay', 'playbook_id': 'tune-temporal-decay', 'recommended_bundle': {'bundle_id': 'temporal-only', 'target_types': ['temporal'], 'target_names': ['time_decay']}}, 'guidance': {'status': 'tune_temporal_decay', 'priority': 'medium', 'recommended_actions': ['adjust_weighting_time_decay'], 'top_reason': 'time_decay'}}}}, f, ensure_ascii=False)
        (status, payload) = self._get_json('/api/avm/health')
        self.assertEqual(status, 200)
        self.assertEqual(payload['calibration_guidance']['status'], 'tune_temporal_decay')
        self.assertEqual(payload['calibration_target_counts'], {'global_risk': 0, 'risk_factor': 0, 'temporal': 1, 'strategy': 0})
        self.assertEqual(payload['top_calibration_target']['name'], 'time_decay')
        self.assertEqual(payload['recommended_bundle_preview_command'], 'python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay')
        self.assertEqual(payload['recommended_bundle_write_command'], 'python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write')
        self.assertEqual(payload['recommended_bundle_patch_preview']['changed_keys'], ['weighting.time_decay'])

    def test_health_diagnostics_merges_partial_embedded_calibration_targets_with_file_context(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump({'radius_km': 3.0, 'weighting': {'distance_power': 2.0, 'time_decay': 0.85, 'community_boost': 1.3}, 'risk_discount_factor': 0.9, 'alert_threshold': 0.25, 'risk_factor_overrides': {'is_occupied': 0.8}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'calibration_targets.json'), 'w', encoding='utf-8') as f:
            json.dump({'config_patch': {'weighting': {'time_decay': 0.72}, 'risk_discount_factor': 0.99, 'risk_factor_overrides': {'is_occupied': 0.5}}, 'temporal_targets': [{'target_type': 'temporal', 'name': 'time_decay', 'suggested_next_value': 0.72}], 'global_risk_targets': [{'target_type': 'global_risk', 'name': 'risk_discount_factor', 'suggested_next_value': 0.99}], 'risk_factor_targets': [{'target_type': 'risk_flag', 'name': 'is_occupied', 'suggested_next_factor': 0.5}], 'strategy_targets': [], 'top_calibration_target': {'target_type': 'risk_flag', 'name': 'is_occupied'}, 'top_calibration_target_hint': {'status': 'tune_risk_factors', 'playbook_id': 'split-bundle-or-single-target-first', 'recommended_bundle': {'bundle_id': 'temporal-global-risk-risk-flag', 'target_types': ['temporal', 'global_risk', 'risk_flag'], 'target_names': ['time_decay', 'risk_discount_factor', 'is_occupied']}, 'suggested_bundle_commands': ['python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied', 'python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied --write', 'python tools/evaluate_avm.py', 'python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report']}, 'guidance': {'status': 'tune_risk_factors', 'priority': 'high', 'recommended_actions': ['split_bundle_or_single_target_first'], 'top_reason': 'multi_flag_bundle'}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump({'evaluation': {'calibration_targets': {'top_calibration_target': {'target_type': 'risk_flag', 'name': 'is_occupied'}}}}, f, ensure_ascii=False)
        (status, payload) = self._get_json('/api/avm/health')
        self.assertEqual(status, 200)
        self.assertEqual(payload['recommended_bundle_risk_level'], 'high')
        self.assertEqual(payload['recommended_bundle_next_action'], 'split_bundle_or_single_target_first')
        self.assertEqual(payload['recommended_bundle_follow_up_command_kind'], 'none')
        self.assertEqual([item['kind'] for item in payload['recommended_bundle_command_chain']], ['preview'])

    def test_health_endpoint_backfills_bundle_commands_from_recommended_bundle_when_suggestions_missing(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump({'radius_km': 3.0, 'weighting': {'distance_power': 2.0, 'time_decay': 0.85, 'community_boost': 1.3}, 'risk_discount_factor': 0.9, 'alert_threshold': 0.25, 'risk_factor_overrides': {}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'calibration_targets.json'), 'w', encoding='utf-8') as f:
            json.dump({'temporal_targets': [{'target_type': 'temporal', 'name': 'time_decay', 'suggested_next_value': 0.72}], 'global_risk_targets': [], 'risk_factor_targets': [], 'strategy_targets': [], 'config_patch': {'weighting': {'time_decay': 0.72}}, 'top_calibration_target': {'target_type': 'temporal', 'name': 'time_decay'}, 'top_calibration_target_hint': {'status': 'tune_temporal_decay', 'target_type': 'temporal', 'target_name': 'time_decay', 'playbook_id': 'tune-temporal-decay', 'runbook_refs': ['tools/evaluate_avm.py'], 'recommended_actions': ['adjust_weighting_time_decay'], 'suggested_commands': ['python tools/evaluate_avm.py'], 'recommended_bundle': {'bundle_id': 'temporal-only', 'target_types': ['temporal'], 'target_names': ['time_decay']}}, 'guidance': {'status': 'tune_temporal_decay', 'priority': 'medium', 'recommended_actions': ['adjust_weighting_time_decay'], 'top_reason': 'time_decay'}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump({'evaluation': {}}, f, ensure_ascii=False)
        (status, payload) = self._get_json('/api/avm/health')
        self.assertEqual(status, 200)
        self.assertEqual(payload['recommended_bundle_preview_command'], 'python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay')
        self.assertEqual(payload['recommended_bundle_write_command'], 'python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write')
        self.assertEqual(payload['recommended_bundle_verify_command'], 'python tools/evaluate_avm.py')
        self.assertEqual(payload['recommended_bundle_gate_command'], 'python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report')
        self.assertEqual(payload['recommended_bundle_next_action'], 'safe_to_write_then_verify')
        self.assertEqual(payload['recommended_bundle_next_action_command'], 'python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write')
        self.assertEqual(payload['recommended_bundle_follow_up_command'], 'python tools/evaluate_avm.py')
        self.assertEqual(payload['recommended_bundle_follow_up_command_kind'], 'verify')
        self.assertEqual([item['kind'] for item in payload['recommended_bundle_command_chain']], ['write', 'verify', 'gate'])

    def test_analysis_release_gate_endpoint_returns_json_error_on_operator_summary_failure(self):
        gate_payload = {'pass': False, 'evaluation': {'pass': False}, 'completeness': {'pass': True}, 'drift': {'pass': True}, 'api_smoke': {'skipped': True}, 'analysis_readiness': {'manual_review_receipt_summary': {'receipt_count': 1}}}
        with mock.patch('tools.avm_release_gate.generate_release_gate_report', return_value=gate_payload), mock.patch.object(server_module, '_avm_operator_eval_summary', side_effect=RuntimeError('boom')):
            with self._open_post('/api/analysis/release_gate', {'window_days': '7', 'min_sample_size': '1', 'smoke_sample_size': '0'}) as response:
                self._assert_collection_job_failed(response.status, json.load(response), 'AVM_RELEASE_GATE_SUMMARY_FAILED')

    def test_health_endpoint_tolerates_non_object_calibration_targets_file(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'calibration_targets.json'), 'w', encoding='utf-8') as f:
            json.dump([], f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump({'evaluation': {}}, f, ensure_ascii=False)
        (status, payload) = self._get_json('/api/avm/health')
        self.assertEqual(status, 200)
        self.assertEqual(payload['calibration_guidance']['status'], 'unavailable')
        self.assertEqual(payload['calibration_target_counts'], {'global_risk': 0, 'risk_factor': 0, 'temporal': 0, 'strategy': 0})
        self.assertEqual(payload['recommended_bundle_next_action'], 'no_action_required')

    def test_health_endpoint_tolerates_non_object_config_file(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump([], f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump({'evaluation': {}}, f, ensure_ascii=False)
        (status, payload) = self._get_json('/api/avm/health')
        self.assertEqual(status, 200)
        self.assertEqual(payload['calibration_guidance']['status'], 'unavailable')
        self.assertEqual(payload['calibration_target_counts'], {'global_risk': 0, 'risk_factor': 0, 'temporal': 0, 'strategy': 0})
        self.assertEqual(payload['recommended_bundle_next_action'], 'no_action_required')

    def test_health_endpoint_tolerates_invalid_object_config_file(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump({'radius_km': -1, 'weighting': {'distance_power': 2.0, 'time_decay': 0.85, 'community_boost': 1.3}, 'risk_discount_factor': 0.9, 'alert_threshold': 0.25, 'risk_factor_overrides': {}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump({'evaluation': {}}, f, ensure_ascii=False)
        (status, payload) = self._get_json('/api/avm/health')
        self.assertEqual(status, 200)
        self.assertEqual(payload['calibration_guidance']['status'], 'unavailable')
        self.assertEqual(payload['calibration_target_counts'], {'global_risk': 0, 'risk_factor': 0, 'temporal': 0, 'strategy': 0})
        self.assertEqual(payload['recommended_bundle_next_action'], 'no_action_required')

    def test_health_endpoint_tolerates_malformed_config_file(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            f.write('{')
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump({'evaluation': {}}, f, ensure_ascii=False)
        (status, payload) = self._get_json('/api/avm/health')
        self.assertEqual(status, 200)
        self.assertEqual(payload['calibration_guidance']['status'], 'unavailable')
        self.assertEqual(payload['calibration_target_counts'], {'global_risk': 0, 'risk_factor': 0, 'temporal': 0, 'strategy': 0})
        self.assertEqual(payload['recommended_bundle_next_action'], 'no_action_required')

    def test_health_endpoint_uses_gate_embedded_calibration_targets_when_file_is_missing(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump({'radius_km': 3.0, 'weighting': {'distance_power': 2.0, 'time_decay': 0.85, 'community_boost': 1.3}, 'risk_discount_factor': 0.9, 'alert_threshold': 0.25, 'risk_factor_overrides': {}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump({'evaluation': {'coordinate_strategy_watchlist': [], 'calibration_targets': {'config_patch': {'weighting': {'time_decay': 0.72}}, 'temporal_targets': [{'target_type': 'temporal', 'name': 'time_decay', 'suggested_next_value': 0.72}], 'global_risk_targets': [], 'risk_factor_targets': [], 'strategy_targets': [], 'top_calibration_target': {'target_type': 'temporal', 'name': 'time_decay'}, 'top_calibration_target_hint': {'status': 'tune_temporal_decay', 'target_type': 'temporal', 'target_name': 'time_decay', 'playbook_id': 'tune-temporal-decay', 'recommended_bundle': {'bundle_id': 'temporal-only', 'target_types': ['temporal'], 'target_names': ['time_decay']}}, 'guidance': {'status': 'tune_temporal_decay', 'priority': 'medium', 'recommended_actions': ['adjust_weighting_time_decay'], 'top_reason': 'time_decay'}}}}, f, ensure_ascii=False)
        (status, payload) = self._get_json('/api/avm/health')
        self.assertEqual(status, 200)
        self.assertEqual(payload['calibration_guidance']['status'], 'tune_temporal_decay')
        self.assertEqual(payload['calibration_target_counts'], {'global_risk': 0, 'risk_factor': 0, 'temporal': 1, 'strategy': 0})
        self.assertEqual(payload['top_calibration_target']['name'], 'time_decay')
        self.assertEqual(payload['recommended_bundle_preview_command'], 'python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay')
        self.assertEqual(payload['recommended_bundle_write_command'], 'python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write')
        self.assertEqual(payload['recommended_bundle_patch_preview']['changed_keys'], ['weighting.time_decay'])

    def test_health_endpoint_merges_partial_embedded_calibration_targets_with_file_context(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump({'radius_km': 3.0, 'weighting': {'distance_power': 2.0, 'time_decay': 0.85, 'community_boost': 1.3}, 'risk_discount_factor': 0.9, 'alert_threshold': 0.25, 'risk_factor_overrides': {'is_occupied': 0.8}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'calibration_targets.json'), 'w', encoding='utf-8') as f:
            json.dump({'config_patch': {'weighting': {'time_decay': 0.72}, 'risk_discount_factor': 0.99, 'risk_factor_overrides': {'is_occupied': 0.5}}, 'temporal_targets': [{'target_type': 'temporal', 'name': 'time_decay', 'suggested_next_value': 0.72}], 'global_risk_targets': [{'target_type': 'global_risk', 'name': 'risk_discount_factor', 'suggested_next_value': 0.99}], 'risk_factor_targets': [{'target_type': 'risk_flag', 'name': 'is_occupied', 'suggested_next_factor': 0.5}], 'strategy_targets': [], 'top_calibration_target': {'target_type': 'risk_flag', 'name': 'is_occupied'}, 'top_calibration_target_hint': {'status': 'tune_risk_factors', 'playbook_id': 'split-bundle-or-single-target-first', 'recommended_bundle': {'bundle_id': 'temporal-global-risk-risk-flag', 'target_types': ['temporal', 'global_risk', 'risk_flag'], 'target_names': ['time_decay', 'risk_discount_factor', 'is_occupied']}, 'suggested_bundle_commands': ['python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied', 'python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied --write', 'python tools/evaluate_avm.py', 'python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report']}, 'guidance': {'status': 'tune_risk_factors', 'priority': 'high', 'recommended_actions': ['split_bundle_or_single_target_first'], 'top_reason': 'multi_flag_bundle'}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump({'evaluation': {'calibration_targets': {'top_calibration_target': {'target_type': 'risk_flag', 'name': 'is_occupied'}}}}, f, ensure_ascii=False)
        (status, payload) = self._get_json('/api/avm/health')
        self.assertEqual(status, 200)
        self.assertEqual(payload['recommended_bundle_risk_level'], 'high')
        self.assertEqual(payload['recommended_bundle_next_action'], 'split_bundle_or_single_target_first')
        self.assertEqual(payload['recommended_bundle_follow_up_command_kind'], 'none')
        self.assertEqual([item['kind'] for item in payload['recommended_bundle_command_chain']], ['preview'])

    def test_analysis_health_alias_endpoint(self):
        (status, payload) = self._get_json('/api/analysis/health')
        self.assertEqual(status, 200)
        self.assertEqual(payload['status'], 'ok')
        self.assertIn('collection_stage', payload)
        self.assertIn('operator_action_summary', payload['collection_stage'])
        self.assertIn('scheduler_feedback_summary', payload['collection_stage'])
        self.assertIn('operator_overview', payload['collection_stage'])
        self.assertIn('manual_review_backlog_summary', payload['collection_stage'])

    def test_analysis_health_alias_returns_json_error_on_health_snapshot_failure(self):
        with mock.patch.object(server_module.AVM_SERVICE, 'health_snapshot', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/analysis/health')
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_HEALTH_FAILED')
        self.assertRegex(body['error']['details']['error_id'], r'^[a-f0-9]{16}$')

    def test_analysis_health_alias_surfaces_risk_validation_summary(self):
        (status, payload) = self._get_json('/api/analysis/health')
        self.assertEqual(status, 200)
        self.assertIn('risk_validation_counts', payload)
        self.assertIn('risk_feature_completeness_avg', payload)
        self.assertIn('active_weighting', payload)
        self.assertIn('active_risk_discount_factor', payload)
        self.assertIn('active_risk_factor_override_count', payload)
        self.assertIn('active_risk_factor_overrides', payload)
        self.assertIn('coordinate_strategy_counts', payload)
        self.assertIn('calibration_guidance', payload)
        self.assertIn('calibration_target_counts', payload)
        self.assertIn('top_calibration_target', payload)
        self.assertIn('top_calibration_target_hint', payload)
        self.assertIn('calibration_patch_preview', payload)
        self.assertIn('top_calibration_patch_preview', payload)
        self.assertIn('recommended_bundle_patch_preview', payload)
        self.assertIn('recommended_bundle_risk_level', payload)
        self.assertIn('recommended_bundle_risk_reasons', payload)
        self.assertIn('recommended_bundle_next_action', payload)
        self.assertIn('recommended_bundle_next_action_reasons', payload)
        self.assertIn('recommended_bundle_next_action_command', payload)
        self.assertIn('recommended_bundle_next_action_command_kind', payload)
        self.assertIn('recommended_bundle_follow_up_command', payload)
        self.assertIn('recommended_bundle_follow_up_command_kind', payload)
        self.assertIn('recommended_bundle_command_chain', payload)
        self.assertIn('coordinate_strategy_watchlist', payload)

__all__ = ["AVMHttpContractPart01"]
