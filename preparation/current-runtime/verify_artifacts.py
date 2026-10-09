"""Verify final analysis exports and endpoint denominators before publication."""
import csv
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
from PIL import Image
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from equivoque.core import read_json,write_json,digest,frozen_hashes
RUN='equivoque-2026-10-09-v1'
output=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else ROOT/'analysis/results'/RUN/'attempt-01'
frozen_hashes()
def rows(name):
    with (output/'tables'/name).open(newline='')as file:return list(csv.DictReader(file))
trials=rows('trials.csv');turns=rows('turns.csv')
schedule=read_json(ROOT/'manifests'/RUN/'schedule.json')['trials']
assert len(trials)==2100
assert {r['trial_id']for r in trials}=={r['trial_id']for r in schedule}
assert all(not r['trial_id'].startswith('calibration/')for r in trials)
assert len({r['trial_id']for r in trials})==2100
missingness=rows('missingness.csv')
assert len(missingness)==42 and all(int(r['assigned'])==50 for r in missingness)
assert sum(int(r['assigned'])for r in missingness)==2100
assert sum(int(r['valid_pre'])for r in missingness)==sum(bool(r.get('pre_impact'))for r in trials)
assert sum(int(r['valid_post'])for r in missingness)==sum(bool(r.get('post_impact'))for r in trials)
captions=read_json(output/'figure_captions.json')
for name,caption in captions.items():
    assert caption
    ET.parse(output/'figures'/(name+'.svg'))
    with Image.open(output/'figures'/(name+'.png'))as image:
        assert image.width>100 and image.height>100
        image.verify()
assert (output/'REPORT.md').stat().st_size>1000
assert (output/'index.html').stat().st_size>1000
assert read_json(output/'union_audit.json')['integrity_ok']
assert not read_json(output/'provenance.json')['incomplete_collection']
calibration=rows('calibration_attempts.csv')
assert sum(int(r['subject_invocations'])for r in calibration)==383
assert sum(r['attempt'].startswith('preflight-helper-')for r in calibration)==10
service_calibration=rows('service_calibration_attempts.csv')
assert sum(int(r['subject_invocations'])for r in service_calibration)==42
provenance=read_json(output/'provenance.json')
assert provenance['development_invocations']==5
assert provenance['non_evaluation_invocations']==430
assert provenance['unknown_duration_turns']==41
assert provenance['unknown_exit_code_turns']==24
assert sum(r['execution_epoch']=='resume-03'for r in trials)==458
assert sum(r['execution_epoch']=='spans-resume-02-resume-03'for r in trials)==13
assert sum(r['execution_epoch']=='spans-expanded-01-resume-02'for r in trials)==8
assert sum(len(read_json(p)['turns']) for p in (ROOT/'results'/RUN).glob('worker-*/trials/*.json'))==len(turns)
import hashlib
archives=list((ROOT/'results'/RUN).glob('worker-*/native-raw-executor-*/*/files.json'))
assert len(archives)==2100
assert {read_json(p)['trial_id']for p in archives}=={r['trial_id']for r in trials}
native_files=0
for path in archives:
    for name,expected in read_json(path)['files'].items():
        data=(path.parent/name).read_bytes()
        assert len(data)==expected['bytes']
        assert hashlib.sha256(data).hexdigest()==expected['sha256']
        native_files+=1
assert native_files==2100+3*len(turns)
report={'passed':True,'trial_rows':len(trials),'returned_turn_rows':len(turns),
        'configuration_frame_cells':len(missingness),'assigned_per_cell':50,
        'svg_png_figure_pairs_verified':len(captions),
        'csv_tables':len(list((output/'tables').glob('*.csv'))),
        'worker_calibration_invocations_excluded':383,'helper_calibration_checks_excluded':10,
        'shared_service_calibration_invocations_excluded':42,'non_evaluation_invocations_excluded':430,
        'terminal_native_archives_verified':len(archives),'exact_native_files_verified':native_files,
        'analysis_sha256':digest(ROOT/'analysis/analyze.py'),'canonical_hashes_unchanged':True}
write_json(output/'artifact_validation.json',report)
print(json.dumps(report,indent=2),flush=True)
