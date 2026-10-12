import subprocess
from equivoque.core import ROOT,read_json
from .protocol import CONFIG,frozen_hashes


def main():
    frozen_hashes();config=read_json(CONFIG)
    if subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip():raise ValueError('Commit source preparation first')
    base=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    for w in config['workers']:
        tree=ROOT/'work/worker-trees'/config['run_id']/w;branch=f"worker/{config['run_id']}/{w}"
        if tree.exists():
            if subprocess.check_output(['git','rev-parse','HEAD'],cwd=tree,text=True).strip()!=base:raise ValueError('Worktree source differs')
            continue
        tree.parent.mkdir(parents=True,exist_ok=True)
        subprocess.run(['git','worktree','add','--no-checkout','-b',branch,str(tree),base],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
        patterns=['/*','!/*/','/equivoque/','/equivoque2/','/experiment2/','/experiment3/','/experiment7/',
                  '/protocol/','/tests/','/scripts/','/preparation/','/manifests/','/results/'+config['run_id']+'/']
        subprocess.run(['git','sparse-checkout','set','--no-cone','--stdin'],input='\n'.join(patterns)+'\n',cwd=tree,text=True,check=True)
        subprocess.run(['git','read-tree','-mu','HEAD'],cwd=tree,check=True)
    print('20 worker worktrees at source '+base)


if __name__=='__main__':main()
