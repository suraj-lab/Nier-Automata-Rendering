"""Future filesystem-writer scenario oracle. No disk access or writer implementation here."""
import json

ORIGINAL = b'; keep comment\r\n[Rendering]\r\nPreset=Custom75\r\n[Other]\r\nKeep=yes\r\n'
UPDATED = ORIGINAL.replace(b'Preset=Custom75', b'Preset=Native')
EXTERNAL = b'[Rendering]\r\nPreset=Native\r\n[External]\r\nKeep=mine\r\n'

# target_bytes=None means absent. Omitted expected fields mean an uncertain observation, not absent.
CASES = [
    {'name':'existing_success', 'initial':ORIGINAL, 'fault':None,
     'expected':{'outcome':'Committed','target_bytes':UPDATED}},
    {'name':'missing_success', 'initial':None, 'fault':None,
     'expected':{'outcome':'Committed','target_bytes':b'[Rendering]\r\nPreset=Native\r\n'}},
    {'name':'snapshot_stale_before_save', 'initial':ORIGINAL, 'external_bytes':EXTERNAL,
     'fault':'before_prepare', 'expected':{'outcome':'PreCommitFailure','target_bytes':EXTERNAL}},
    {'name':'snapshot_stale_after_stage', 'initial':ORIGINAL, 'external_bytes':EXTERNAL,
     'fault':'before_publish_recheck', 'expected':{'outcome':'PreCommitFailure','target_bytes':EXTERNAL}},
    {'name':'stage_write_failure', 'initial':ORIGINAL, 'fault':'stage_write',
     'expected':{'outcome':'PreCommitFailure','target_bytes':ORIGINAL}},
    {'name':'stage_flush_failure', 'initial':ORIGINAL, 'fault':'stage_flush',
     'expected':{'outcome':'PreCommitFailure','target_bytes':ORIGINAL}},
    {'name':'stage_close_failure', 'initial':ORIGINAL, 'fault':'stage_close',
     'expected':{'outcome':'PreCommitFailure','target_bytes':ORIGINAL}},
    {'name':'stage_security_failure', 'initial':ORIGINAL, 'fault':'before_stage_contents',
     'expected':{'outcome':'PreCommitFailure','target_bytes':ORIGINAL,'stage_contains_original':False}},
    {'name':'stage_reader_rejects', 'initial':ORIGINAL, 'fault':'stage_reader_validation',
     'expected':{'outcome':'PreCommitFailure','target_bytes':ORIGINAL}},
    {'name':'replacement_rejected_without_move', 'initial':ORIGINAL, 'fault':'replace_unchanged',
     'expected':{'outcome':'PreCommitFailure','target_bytes':ORIGINAL}},
    {'name':'replacement_failed_original_moved', 'initial':ORIGINAL, 'fault':'replace_original_moved',
     'expected':{'outcome':'RecoveryRequired','target_bytes':None,'backup_bytes':ORIGINAL}},
    {'name':'published_but_final_observation_failed', 'initial':ORIGINAL, 'fault':'after_publish_observation',
     'expected':{'outcome':'RecoveryRequired','target_bytes':UPDATED,'backup_bytes':ORIGINAL}},
    {'name':'missing_target_created_concurrently', 'initial':None, 'external_bytes':EXTERNAL,
     'fault':'atomic_missing_publish', 'expected':{'outcome':'PreCommitFailure','target_bytes':EXTERNAL}},
]


def assert_observation(case, observed):
    """Assert an observation returned by the future real-code fixture adapter."""
    outcome = observed['outcome']
    assert outcome in ('PreCommitFailure','Committed','RecoveryRequired')
    for key, value in case['expected'].items():
        assert key in observed and observed[key] == value, (case['name'], key)
    assert observed['can_claim_saved'] is (outcome == 'Committed'), case['name']
    assert observed['foreign_files_unchanged'] is True, case['name']
    if outcome == 'RecoveryRequired':
        assert observed['recovery_paths'], case['name']
        assert case['initial'] in (observed.get('target_bytes'), observed.get('backup_bytes')), case['name']


def selfcheck():
    # Synthetic observations below test the oracle only. They are not writer behavior/evidence.
    checked = 0
    for case in CASES:
        observation = dict(case['expected'], can_claim_saved=case['expected']['outcome']=='Committed',
                           foreign_files_unchanged=True, recovery_paths=['owned-backup'] if
                           case['expected']['outcome']=='RecoveryRequired' else [])
        assert_observation(case, observation)
        for invalid in [dict(observation,can_claim_saved=not observation['can_claim_saved']),
                        dict(observation,foreign_files_unchanged=False),
                        dict(observation,outcome='MadeUp')]:
            try:
                assert_observation(case,invalid)
            except AssertionError:
                checked += 1
            else:
                raise AssertionError('Oracle accepted a deliberately invalid observation')
    print(json.dumps({'case_definitions':len(CASES),'oracle_rejections':checked,
                      'writer_executed':False,'writer_implemented':False}))


if __name__ == '__main__':
    selfcheck()
