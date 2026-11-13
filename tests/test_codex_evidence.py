import unittest
from types import SimpleNamespace
from maker_elegoo.codex_evidence import build_codex_evidence, validate_codex_recommendations

class EvidenceTests(unittest.TestCase):
    def test_allowlist_excludes_identifiers_and_geometry(self):
        project = SimpleNamespace(path='C:/secret/face.3mf', objects=('Private face',), source_settings={'enable_support':'0'}, filaments=(SimpleNamespace(material='PLA', profile='Secret'),))
        plan = SimpleNamespace(machine_settings={'printer_model':'Elegoo Centauri Carbon 2','nozzle_diameter':['0.4']}, process_settings={'enable_support':'0','support_on_build_plate_only':'1','wall_loops':'3'}, unmapped={'path':'C:/secret/face.3mf','foo':'<vertex x="1"/>'})
        result = SimpleNamespace(success=True, validation=SimpleNamespace(success=True,warnings=('C:/secret/face.3mf',),estimated_seconds=3600,filament_grams=12.5),geometry=SimpleNamespace(unchanged=True))
        payload=build_codex_evidence(project,plan,result)
        rendered=str(payload)
        for secret in ('face.3mf','Private face','<vertex','Secret','C:/secret'):
            self.assertNotIn(secret,rendered)
        self.assertEqual(payload['slicing']['estimated_seconds'],3600)

    def test_recommendations_reject_unknown_or_unsliced_orientation_and_unsafe_support(self):
        plan=SimpleNamespace(process_settings={'enable_support':'0','support_on_build_plate_only':'1'},unmapped={})
        good=SimpleNamespace(label='side',valid=True,is_current=False)
        bad=SimpleNamespace(label='bad',valid=True,is_current=False)
        orientation=SimpleNamespace(current=SimpleNamespace(candidate=SimpleNamespace(label='current',valid=True,is_current=True),result=SimpleNamespace(success=True)),alternatives=(SimpleNamespace(candidate=good,result=SimpleNamespace(success=True,geometry=SimpleNamespace(unchanged=True))),SimpleNamespace(candidate=bad,result=SimpleNamespace(success=False))),recommended=good)
        raw={'suggestions':[{'kind':'feature','source_key':'','target_key':'enable_support','value':'1','reason':'Try support','confidence':'medium'},{'kind':'feature','source_key':'','target_key':'support_type','value':'tree','reason':'No','confidence':'high'}],'orientation_id':'bad'}
        suggestions,candidate=validate_codex_recommendations(raw,plan,orientation)
        self.assertEqual(len(suggestions),1)
        self.assertIsNone(candidate)
        raw['orientation_id']='side'
        self.assertIs(validate_codex_recommendations(raw,plan,orientation)[1],good)
        raw['orientation_id']='current'
        self.assertIsNone(validate_codex_recommendations(raw,plan,orientation)[1])




    def test_support_requires_real_successful_comparison(self):
        from unittest.mock import patch
        from maker_elegoo.codex_evidence import verify_support_recommendation
        from maker_elegoo.ai import Suggestion
        from pathlib import Path
        from dataclasses import dataclass
        @dataclass
        class Plan:
            process_settings: dict
        plan=Plan({'enable_support':'0','support_on_build_plate_only':'1'})
        suggestion=Suggestion('feature','','enable_support','1','Supports','medium')
        result=SimpleNamespace(success=True,geometry=SimpleNamespace(unchanged=True),validation=None)
        project=SimpleNamespace(path=Path('source.3mf'))
        failed=SimpleNamespace(success=False,geometry=SimpleNamespace(unchanged=True),validation=None)
        with patch('maker_elegoo.codex_evidence.convert_project',return_value=failed) as convert:
            report=verify_support_recommendation(project,plan,result,suggestion,object())
        self.assertFalse(report['verified'])
        self.assertEqual(convert.call_args.args[1].process_settings['enable_support'],'1')
        self.assertEqual(plan.process_settings['enable_support'],'0')

    def test_successful_proposal_cannot_validate_failed_baseline(self):
        from unittest.mock import patch
        from maker_elegoo.codex_evidence import verify_process_recommendation
        from maker_elegoo.ai import Suggestion
        from pathlib import Path
        from dataclasses import dataclass
        @dataclass
        class Plan:
            process_settings: dict
        plan=Plan({'enable_support':'0'})
        suggestion=Suggestion('feature','','enable_support','1','Supports','medium')
        baseline=SimpleNamespace(success=False,geometry=SimpleNamespace(unchanged=True),validation=None)
        passed=SimpleNamespace(success=True,geometry=SimpleNamespace(unchanged=True),validation=None)
        with patch('maker_elegoo.codex_evidence.convert_project',return_value=passed):
            report=verify_process_recommendation(SimpleNamespace(path=Path('source.3mf')),
                                                 plan,baseline,suggestion,object())
        self.assertFalse(report['verified'])

    def test_evidence_uses_target_filament_materials_when_present(self):
        project = SimpleNamespace(path='source.3mf', objects=(), source_settings={},
                                  filaments=(SimpleNamespace(material='PLA', profile=''),))
        plan = SimpleNamespace(
            machine_settings={'printer_model': 'Elegoo Centauri Carbon 2', 'nozzle_diameter': ['0.4']},
            process_settings={'wall_loops': '2'},
            filament_settings=({'filament_type': ['ABS']},),
            unmapped={},
        )
        result = SimpleNamespace(success=True, validation=None, geometry=None)
        payload = build_codex_evidence(project, plan, result)
        self.assertEqual(payload['materials'], ['ABS'])
        self.assertEqual(payload['source_materials'], ['PLA'])



