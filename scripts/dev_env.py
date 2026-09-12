"""Write a .env for local development with freshly generated keys.

    uv run python scripts/dev_env.py            # creates .env (refuses to overwrite)
    uv run python scripts/dev_env.py --force    # regenerates; existing encrypted rows become unreadable
"""

import secrets
import sys
from pathlib import Path

from cryptography.fernet import Fernet

path = Path(__file__).resolve().parent.parent / ".env"
if path.exists() and "--force" not in sys.argv:
    sys.exit(f"{path} exists; pass --force to replace it (the old keys can no longer decrypt the dev DB)")

path.write_text(f"""EA_ENV=dev
EA_DATABASE_URL=sqlite+aiosqlite:///./exposure_auditor.db
EA_JWT_SECRET={secrets.token_urlsafe(48)}
EA_FIELD_ENCRYPTION_KEY={Fernet.generate_key().decode()}
EA_BLIND_INDEX_KEY={secrets.token_urlsafe(48)}
EA_VERIFICATION_DELIVERY=console

# Used by docker-compose.yml for the local Postgres service.
POSTGRES_PASSWORD={secrets.token_urlsafe(24)}

# Scans: Claude through one of three providers.
#   bedrock   - your normal AWS credentials (AWS_PROFILE etc.) and EA_BEDROCK_REGION
#   foundry   - EA_FOUNDRY_RESOURCE and EA_FOUNDRY_API_KEY
#   anthropic - EA_ANTHROPIC_API_KEY (or ANTHROPIC_API_KEY)
EA_LLM_PROVIDER=bedrock
EA_BEDROCK_REGION=eu-central-1
# EA_MODEL_ID defaults per provider; set it only to pin a different model.

# Optional providers. Leave commented out to run without them.
# EA_HIBP_API_KEY=
# EA_BRAVE_API_KEY=
""")
path.chmod(0o600)
print(f"wrote {path}")
