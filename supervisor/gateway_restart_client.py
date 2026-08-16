#!/usr/bin/env python3
import argparse, json, secrets, socket, time

def main():
    p=argparse.ArgumentParser(description="Submit one fixed Hermes gateway restart request")
    p.add_argument("task_id"); p.add_argument("--socket",required=True); p.add_argument("--board",required=True)
    p.add_argument("--nonce"); p.add_argument("--execute",action="store_true",help="perform restart; default is dry-run")
    a=p.parse_args()
    request={"version":1,"task_id":a.task_id,"nonce":a.nonce or secrets.token_urlsafe(32),"service":"hermes-gateway.service","board":a.board,"created_at":int(time.time()),"dry_run":not a.execute}
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
        s.settimeout(60); s.connect(a.socket); s.sendall(json.dumps(request,separators=(",",":")).encode()); s.shutdown(socket.SHUT_WR)
        response=s.recv(65536)
    print(response.decode().strip())
    raise SystemExit(0 if json.loads(response)["ok"] else 1)
if __name__=="__main__": main()
