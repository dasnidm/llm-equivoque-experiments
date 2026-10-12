"""Data-only audit, local integration and lossless raw archive packaging."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
from equivoque.core import ROOT,digest,read_json,write_json
from .protocol import CONFIG,frozen_hashes
from .audit import audit_worker


def git(root,*args):return subprocess.check_output(['git',*args],cwd=root,text=True).strip()


def make_archive(source,path,prefix):
    source,path=Path(source),Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    paths=[p for p in sorted(source.rglob('*')) if p.is_file() and not p.name.endswith('.lock')]
    expected={str(Path(prefix)/p.relative_to(source)):digest(p) for p in paths}
    if path.exists():raise ValueError('Archive already exists; verify rather than overwrite')
    with tarfile.open(path,'w:gz') as archive:
        for p in paths:archive.add(p,arcname=str(Path(prefix)/p.relative_to(source)),recursive=False)
    with tarfile.open(path,'r:gz') as archive:
        observed={m.name:hashlib.sha256(archive.extractfile(m).read()).hexdigest() for m in archive.getmembers() if m.isfile()}
    if observed!=expected:raise ValueError('Archive byte identity failed')
    manifest=path.with_name(path.name.replace('.tar.gz','.manifest.json'))
    write_json(manifest,{'archive':path.name,'sha256':digest(path),'raw_file_count':len(expected),'files':expected})
    return {'archive':str(path),'manifest':str(manifest),'sha256':digest(path),'raw_files':len(expected)}


def main():
    frozen_hashes();config=read_json(CONFIG);run=config['run_id'];runtime=ROOT/'sequence_replication/runtime'
    progress=read_json(runtime/'collection-progress.json')
    if len(progress['finished_workers'])!=len(config['workers']):raise ValueError('Workers still active')
    base=git(ROOT,'rev-parse','HEAD');heads=[];audits=[]
    for w in config['workers']:
        tree=ROOT/'work/worker-trees'/run/w;out=tree/'results'/run/f'worker-{w}'
        audit=audit_worker(tree/'manifests'/run/f'worker-{w}.json',out)
        if not audit['integrity_ok']:raise ValueError('Worker raw audit failed '+w+': '+str(audit['errors'][:2]))
        if any(read_json(p)['status']=='active' for p in (out/'trials').glob('*.json')):raise ValueError('Active state remains')
        write_json(out/'audit.json',audit);audits.append(audit)
        (out/'COMPLETION.md').write_text('# Sequence pilot worker '+w.upper()+'\n\nAssigned: '+str(audit['assigned'])+'. Status counts: '+json.dumps(audit['counts'])+'.\n\nEvaluation invocations: '+str(audit['subject_invocations'])+'. Valid pre-disclosure ratings: '+str(audit['valid_measurements'])+'.\n\nExact stimuli, round-specific targets, native files and journals passed audit. Calibration is excluded. No replacement or uncertain replay.\n')
        subprocess.run(['git','add','--sparse','--','results/'+run+'/worker-'+w],cwd=tree,check=True)
        if subprocess.run(['git','diff','--cached','--quiet'],cwd=tree).returncode:
            subprocess.run(['git','commit','-m','Finalize sequence pilot worker '+w.upper()],cwd=tree,check=True,stdout=subprocess.DEVNULL)
        heads.append({'worker':w,'head':git(tree,'rev-parse','HEAD')})
    integration=ROOT/'work/integration-trees'/run
    if integration.exists():raise ValueError('Integration tree already exists')
    integration.parent.mkdir(parents=True,exist_ok=True)
    subprocess.run(['git','worktree','add','--no-checkout','-b','integration/'+run,str(integration),base],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
    patterns=['/*','!/*/','/equivoque/','/equivoque2/','/experiment2/','/experiment3/','/experiment7/','/sequence_replication/','/protocol/','/tests/','/scripts/','/preparation/','/manifests/','/results/'+run+'/','/analysis/results/'+run+'/']
    subprocess.run(['git','sparse-checkout','set','--no-cone','--stdin'],input='\n'.join(patterns)+'\n',cwd=integration,text=True,check=True)
    subprocess.run(['git','read-tree','-mu','HEAD'],cwd=integration,check=True)
    for item in heads:subprocess.run(['git','merge','--no-ff','-m','Integrate sequence pilot worker '+item['worker'].upper(),item['head']],cwd=integration,check=True,stdout=subprocess.DEVNULL)
    shutil.copytree(runtime,integration/'sequence_replication/runtime',dirs_exist_ok=True)
    write_json(integration/'sequence_replication/runtime/local-integration.json',{'source_commit':base,'worker_heads':heads,'data_head':git(integration,'rev-parse','HEAD'),'audits':audits})
    subprocess.run(['git','add','--sparse','sequence_replication/runtime'],cwd=integration,check=True)
    subprocess.run(['git','commit','-m','Preserve sequence pilot readiness and collection ledger'],cwd=integration,check=True,stdout=subprocess.DEVNULL)
    archives=[]
    for w in config['workers']:
        source=integration/'results'/run/f'worker-{w}'
        path=integration/'results'/run/'raw-archives'/f'worker-{w}.tar.gz'
        archives.append(make_archive(source,path,f'worker-{w}'))
    archives.append(make_archive(integration/'sequence_replication/runtime',integration/'results'/run/'raw-archives/coordinator-runtime.tar.gz','sequence_replication/runtime'))
    write_json(integration/'results'/run/'raw-archives/index.json',{'run_id':run,'archives':archives,'representation':'Lossless raw file archives; each manifest verifies original bytes. Local integration also retains every unpacked file.'})
    write_json(runtime/'local-finalization.json',{'integration_tree':str(integration),'source_commit':base,'worker_heads':heads,'raw_data_head':git(integration,'rev-parse','HEAD'),'archives':archives})
    print(json.dumps({'integration_tree':str(integration),'workers':len(config['workers']),'archives':len(archives),'raw_files':sum(a['raw_files'] for a in archives)}))


if __name__=='__main__':main()
