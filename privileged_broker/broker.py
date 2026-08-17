#!/usr/bin/python3
"""Installed root-owned CLI. Approval intentionally requires pkexec authentication."""
import argparse, json, os, secrets, stat, sys, time
from pathlib import Path
sys.path.insert(0, '/usr/local/lib/hermes-privileged-broker')
from core import OllamaBackend, approve, canonical, digest, execute, file_identity, make_request, sealed_package

STATE=Path('/var/lib/hermes-privileged-broker')
DB=Path('/home/kvn/.hermes/kanban/boards/zer0-company/kanban.db')
CAPTAIN_UID=1000
REQUEST_ROOT=STATE/'requests'

def load(path, allowed_uid=0):
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  st=os.fstat(fd)
  if not stat.S_ISREG(st.st_mode) or st.st_uid!=allowed_uid or st.st_mode&0o022: raise SystemExit('unsafe file ownership/mode')
  chunks=[]
  while True:
   chunk=os.read(fd,1024*1024)
   if not chunk: break
   chunks.append(chunk)
   if sum(map(len,chunks))>1024*1024: raise SystemExit('file too large')
  return json.loads(b''.join(chunks))
 finally: os.close(fd)
def load_captain_request(path):
 candidate=Path(path)
 if candidate.parent.resolve(strict=True)!=REQUEST_ROOT.resolve(strict=True): raise SystemExit('request must be directly under sealed request root')
 return load(candidate,0)
def key():
 value=load_bytes(STATE/'approval.key')
 if len(value)!=32: raise SystemExit('invalid authority key')
 return value
def load_bytes(path):
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  st=os.fstat(fd)
  if not stat.S_ISREG(st.st_mode) or st.st_uid!=0 or st.st_mode&0o077: raise SystemExit('unsafe authority key')
  return os.read(fd,64)
 finally: os.close(fd)
def main():
 p=argparse.ArgumentParser(); s=p.add_subparsers(dest='cmd',required=True)
 c=s.add_parser('create-request'); c.add_argument('--task',required=True); c.add_argument('--run',required=True,type=int); c.add_argument('--output',required=True); c.add_argument('--package',required=True); c.add_argument('--manifest-sha256',required=True)
 a=s.add_parser('approve'); a.add_argument('request')
 x=s.add_parser('execute')
 args=p.parse_args()
 if args.cmd=='create-request':
  # Seal the complete live effective unit/process/listener/model-store state into the request.
  pre_state=OllamaBackend().capture_pre_state(DB,(CAPTAIN_UID,))
  req=make_request(args.task,args.run,secrets.token_urlsafe(32),int(time.time()),pre_state=pre_state,package=sealed_package(str(Path(args.package).resolve(strict=True)),args.manifest_sha256)); Path(args.output).write_bytes(canonical(req)+b'\n'); print(digest(req)); return
 if os.geteuid()!=0: raise SystemExit('approve/execute must run through installed pkexec/sudo policy')
 if args.cmd=='approve':
  if int(os.environ.get('PKEXEC_UID','-1')) != CAPTAIN_UID: raise SystemExit('non-Captain pkexec identity')
  req=load_captain_request(args.request); print(json.dumps({'request_sha256':digest(req),'requester_task':req['requester_task'],'requester_run':req['requester_run'],'captain_uid':CAPTAIN_UID,'operation':req['fixed_operation'],'host':req['target_host'],'risk':'system Ollama restart; brief local API outage','rollback':req['rollback'],'expires_at':req['expires_at']},indent=2))
  if input('Type the full request SHA-256 to approve: ').strip()!=digest(req): raise SystemExit('denied')
  print(json.dumps(approve(req,db=DB,key=key(),approvals=STATE/'approvals.jsonl',captain_uid=CAPTAIN_UID,now=int(time.time()),queue=STATE/'queue/request.json'),sort_keys=True)); return
 # No arguments: root executor consumes the sole root-owned queue packet.
 queue=STATE/'queue/request.json'
 req=load(queue)
 result=execute(req,db=DB,key=key(),approvals=STATE/'approvals.jsonl',ledger=STATE/'ledger.jsonl',lock=STATE/'execute.lock',now=int(time.time()),backend=OllamaBackend())
 print(json.dumps(result,sort_keys=True)); raise SystemExit(0 if result['ok'] else 1)
if __name__=='__main__': main()
