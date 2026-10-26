"""Genera .env sin sobrescribir un archivo existente. Solo biblioteca estándar."""

from pathlib import Path
import secrets
import os

root = Path(__file__).resolve().parents[1]
password = secrets.token_hex(24)
content = (root / ".env.example").read_text()
content = content.replace("MYSQL_PASSWORD=GENERATE_ME", "MYSQL_PASSWORD=" + password)
content = content.replace("MYSQL_ROOT_PASSWORD=GENERATE_ME", "MYSQL_ROOT_PASSWORD=" + secrets.token_hex(32))
content = content.replace("ghibli:GENERATE_ME@", "ghibli:" + password + "@")
content = content.replace("JWT_SECRET_KEY=GENERATE_ME", "JWT_SECRET_KEY=" + secrets.token_hex(48))
fd = os.open(root / ".env", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as stream:
    stream.write(content)
print(".env creado. No subirlo a Git.")
