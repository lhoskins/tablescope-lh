---
name: testing-tablescope-live
description: Validate platform-admin and tenant-scoped features against the live EC2 deployment at app.tablescope.cloud.
---

# Testing Tablescope on the live EC2 deployment

Use this skill when verifying full-stack changes that are already deployed to the `app.tablescope.cloud` EC2 instance.

## Devin secrets needed

- `TABLESCOPE_SSH_KEY` (personal) — for `ubuntu@13.57.117.13`; may not work if the key is stale, so EC2 Instance Connect is the reliable fallback.
- `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` (org) — for EC2 Instance Connect and temporary security-group ingress.
- `SUPABASE_ANON_KEY` (org) — only if testing the Supabase auth exchange path directly.

## One-time access setup

1. Get the Devin egress IP:
   ```bash
   curl -s https://checkip.amazonaws.com
   ```
2. Open port 22 on the EC2 security group (`sg-0229fe8ffd5a94f72`):
   ```bash
   aws ec2 authorize-security-group-ingress --group-id sg-0229fe8ffd5a94f72 --protocol tcp --port 22 --cidr <DEVIN_IP>/32 --region us-west-1
   ```
3. Generate a temporary RSA key for EC2 Instance Connect:
   ```bash
   ssh-keygen -t rsa -b 4096 -f ~/.ssh/devin_eic_rsa -N ""
   aws ec2-instance-connect send-ssh-public-key \
     --instance-id i-0d1ae6093692f8889 \
     --instance-os-user ubuntu \
     --ssh-public-key "$(cat ~/.ssh/devin_eic_rsa.pub)" \
     --availability-zone us-west-1a \
     --region us-west-1
   ```
4. SSH into the host:
   ```bash
   ssh -i ~/.ssh/devin_eic_rsa -o StrictHostKeyChecking=no ubuntu@13.57.117.13
   ```
   Each `send-ssh-public-key` call is valid for 60 seconds; repeat before each new SSH command if necessary.

## Deploy a branch

On the EC2 host:

```bash
cd /home/ubuntu/tablescope
git fetch origin <branch>
git checkout -B <branch> origin/<branch>
bash deploy_feat.sh
```

`deploy_feat.sh` builds `platform-api` and `web-ui`, recreates `platform-api`, `platform-api-worker`, and `web-ui`, and runs `alembic upgrade head`.

### GPU AI-server image deploy

The GPU AI server (`i-0d938409d1b57ff12`, `32.186.54.52`) has no outbound internet, so build the `ai-server` images on the app EC2 and transfer them to the GPU host:

```bash
# On app EC2 (13.57.117.13)
cd /home/ubuntu/tablescope/ai-server
docker compose build tablescope-ai-api ai-worker
docker save ai-server-tablescope-ai-api:latest ai-server-ai-worker:latest | gzip > /tmp/ai-images.tar.gz

# Transfer to the GPU host and load/recreate
scp /tmp/ai-images.tar.gz ubuntu@32.186.54.52:/home/ubuntu/ai-images.tar.gz
ssh ubuntu@32.186.54.52 '
  cd /home/ubuntu/tablescope/ai-server
  docker load -i /home/ubuntu/ai-images.tar.gz
  docker compose up -d --no-deps tablescope-ai-api ai-worker
  curl -s http://localhost:8000/health
'
```

## Authenticating for UI tests

The live environment enforces Twilio SMS MFA for admin-tier roles. The simplest test harness is to mint a short-lived JWT inside the `platform-api` container using the runtime `JWT_SECRET_KEY`:

```bash
cd /home/ubuntu/tablescope
docker compose exec -T platform-api python - <<'PY'
import os
from datetime import datetime, timezone, timedelta
from jose import jwt

secret = os.environ['JWT_SECRET_KEY']
issuer = os.environ.get('JWT_ISSUER', 'tablescope-platform-api')
audience = os.environ.get('JWT_AUDIENCE', 'tablescope-clients')

def mint(user_id, tenant_id, role, is_super=False, email='test@tablescope.local', aal='aal2'):
    now = datetime.now(timezone.utc)
    payload = {
        'sub': email,
        'tenant_id': tenant_id,
        'org_id': tenant_id,
        'user_id': user_id,
        'role': role,
        'permissions': [],
        'iss': issuer,
        'aud': audience,
        'iat': int(now.timestamp()),
        'exp': int((now.timestamp()) + 3600),
        'aal': aal,
    }
    return jwt.encode(payload, secret, algorithm='HS256')

print(mint(user_id=23, tenant_id=18, role='root_admin'))
print(mint(user_id=28, tenant_id=20, role='tenant_admin'))
PY
```

- Find candidate `user_id`, `tenant_id`, and `role` values with:
  ```bash
  docker compose exec -T db psql -U tablescope -d tablescope -c "SELECT id, email, tenant_id, role, is_super_admin FROM users ORDER BY id LIMIT 50;"
  ```
- `root_admin` or `is_super_admin=true` is needed for `Platform Administration` features.
- `tenant_admin` is useful for negative-authorization tests.
- Set `aal='aal2'` to satisfy the admin MFA gate without using Twilio.

Inject the token into the browser before navigating:

```javascript
window.localStorage.setItem('tablescope.token', '<TOKEN>');
window.localStorage.setItem('tablescope.user_meta', JSON.stringify({
  role: 'root_admin',
  is_super_admin: false,
  tenant_id: 18,
  user_id: 23,
  tenant_slug: 'root'
}));
```

Then navigate to the page under test.

## Seeding read-only test data

For inventory-style features, insert rows via `psql` and remove them after the test:

```bash
docker compose exec -T db psql -U tablescope -d tablescope <<'SQL'
INSERT INTO llm_runtime_targets (name, runtime_type, host, version, status, is_reachable, max_loaded_models, keep_alive_minutes, labels)
VALUES ('Test Target', 'ollama', 'http://ollama:11434', '0.0.1', 'active', true, 1, 5, '{}');
SQL
```

## Testing Ask Anything / conversational analytics

- Use deep-link URLs to exercise exact prompts reliably, because typing long questions into the AI Assistant composer can be truncated or submitted early:
  ```
  https://app.tablescope.cloud/ai?projectId=<PROJECT_ID>&q=<URL_ENCODED_QUESTION>
  https://app.tablescope.cloud/business-insight?q=<URL_ENCODED_QUESTION>
  ```
- The Business Insight Ask Anything flow is synchronous; the "TableScope is thinking…" state can last 60–180 seconds. Wait for a response before interacting again.
- If a turn stays in "Working on it…" or "TableScope is thinking…" indefinitely, check the `platform-api` logs and `analytics_conversation_turns`:
  ```bash
  docker compose logs --tail=50 platform-api
  docker compose exec -T db psql -U tablescope -d tablescope -c "SELECT id, conversation_id, status, error_code, LEFT(assistant_message, 120) FROM analytics_conversation_turns ORDER BY id DESC LIMIT 10;"
  ```
- `Object of type datetime is not JSON serializable` in `platform-api` means a query returned `datetime`/`date` columns and `result_cache` could not be persisted; this should now be handled by JSON-safe row serialization, but if it recurs, rephrase the question to avoid raw date columns (e.g., ask for counts or sums grouped by string columns).
- Reference Library grounding reaches the model through `reference_documents` in the prompt; verify the response names a Reference Library document title. If the answer instead cites insight cards, the reference-doc context may not be rendered.
- Fallback turns expose `error_code` and failure details in `result_metadata`/`result_cache` rather than the user message. If user-facing prose cites an unrelated insight card, the insight-card scorer may be over-matching on generic terms like "cost" or "rate".
- To verify that `datetime`/`date` columns serialize correctly after the `result_profiling.py` fix, ask a question that is known to return date/time values, e.g. `Show me the latest backup start time for each IT system` (project 44). Check `result_metadata.datetimeColumns` is populated and the turn status is `success` with no `Object of type datetime is not JSON serializable` traceback.
- If the Reference Library question returns a fallback with `error_code = live_query_fallback_generation_error` and `fallbackErrorDetails` mentioning an AI server 422, the user-facing prose may still cite Reference Library documents when the fallback prompt includes them; verify by checking that the assistant message names a document title and does not rely solely on unrelated insight cards.
- Phase D document Q&A: verify `turn.intent_type = 'document_qa'`, `error_code IS NULL`, `sql IS NULL`, and `result_metadata->'documentQa'->>'referenceDocumentCount'` is >0. If `referenceDocumentCount` is 0 but the answer mentions documents, the Postgres `plainto_tsquery` in `_reference_documents_for_question` may be over-constrained by filler words ("List", "What does", "Tell me more about"). A title-only or keyword-only phrasing should return a positive count and a correctly grounded answer.

## Cleanup checklist

1. Delete any test rows inserted during the test.
2. Revoke the temporary security-group ingress:
   ```bash
   aws ec2 revoke-security-group-ingress --group-id sg-0229fe8ffd5a94f72 --security-group-rule-ids <SGR_ID> --region us-west-1
   ```
3. Remove temporary local keys:
   ```bash
   rm -f ~/.ssh/devin_eic_rsa ~/.ssh/devin_eic_rsa.pub
   ```

## Common gotchas

- `nginx` may cache the old `web-ui`/`platform-api` Docker IP after a recreate. Run `docker compose exec -T nginx nginx -s reload` if pages 502.
- `pytest` cannot run on the local Devin VM because the VM interpreter is Python 3.10 and the codebase uses `datetime.UTC` (Python 3.11+). Rely on the Docker container / CI for Python tests.
- `SERVICE_API_KEYS` is not always set in `.env`, so service-to-service auth may not be exercisable live; use the root-admin JWT harness instead.
