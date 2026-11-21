"""Judge the latest audit's disagreements with Claude Sonnet (Gemini/agy is unavailable)."""
from pydantic import BaseModel
import anthropic
from tremor.config import load_config, load_dotenv
from tremor.storage import connect
from tremor.taxonomy import default_taxonomy
from tremor import audit
from tremor.refine import Usage, record_spend

class Ruling(BaseModel):
    id: int
    keep: bool
    confident: bool
    reason: str

class Rulings(BaseModel):
    rulings: list[Ruling]

load_dotenv(); cfg = load_config(); conn = connect(cfg.storage_path)
client = anthropic.Anthropic(max_retries=8)
MODEL = cfg.rationale_model

def runner(prompt, schema, model):
    with client.messages.stream(model=MODEL, max_tokens=16000, messages=[{"role": "user", "content": prompt}],
                                output_format=Rulings) as s:
        msg = s.get_final_message()
    u = msg.usage
    record_spend(conn, Usage(MODEL, u.input_tokens, u.output_tokens), "audit-judge"); conn.commit()
    print("tokens", u.input_tokens, u.output_tokens)
    return msg.parsed_output.model_dump()

rid = conn.execute("SELECT run_id FROM audit_runs ORDER BY created_at DESC LIMIT 1").fetchone()[0]
res = audit.judge(conn, default_taxonomy().first_slice(), rid, runner=runner, model=MODEL)
from collections import Counter
print(rid, Counter((r["codex_keep"], r["judge_keep"]) for r in res))
