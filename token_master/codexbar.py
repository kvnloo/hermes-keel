"""Read-only CodexBar adapter. Output is deliberately reduced to numeric counters."""
import json, subprocess
from dataclasses import dataclass
from typing import Any
from .core import Snapshot

@dataclass
class CodexBarCollector:
    executable: str = "codexbar"
    timeout: int = 30
    def collect(self, provider: str = "all") -> list[Snapshot]:
        p=subprocess.run([self.executable,"usage","--provider",provider,"--format","json","--no-color"], capture_output=True, text=True, timeout=self.timeout, check=True)
        raw=json.loads(p.stdout); now=__import__('time').time()
        rows=raw if isinstance(raw,list) else raw.get("providers", raw.get("data", []))
        if isinstance(rows,dict): rows=[dict(v, provider=k) if isinstance(v,dict) else {"provider":k,"value":v} for k,v in rows.items()]
        result=[]
        for row in rows:
            if not isinstance(row,dict): continue
            name=str(row.get("provider") or row.get("name") or "unknown")
            # Never retain labels, account IDs, URLs, or raw payloads.
            used=_number(row, ("used_tokens","usedTokens","tokens_used"))
            limit=_number(row, ("limit_tokens","limitTokens","tokens_limit"))
            result.append(Snapshot(name,now,used,limit,str(row.get("source") or "codexbar")))
        return result

def _number(row: dict[str,Any], names: tuple[str,...]):
    for name in names:
        value=row.get(name)
        if isinstance(value,(int,float)) and value >= 0: return int(value)
    return None
