import os
import json
import hmac
import hashlib
import sqlite3
from dotenv import dotenv_values
from rich.console import Console

console = Console()


def hash(key, msg):
    return hmac.new(
        key=key.encode("utf-8"),
        msg=msg.encode("utf-8"),
        digestmod=hashlib.sha512,
    ).hexdigest()


token_name = "a2a-agent"
project_root = "D:/code/a2a/a2a-strapi"
project_origin = "http://localhost:1337"

conn = sqlite3.connect(f"{project_root}/.tmp/data.db")

cursor = conn.cursor()

cursor.execute("SELECT type, id FROM strapi_api_tokens WHERE name = ?", (token_name,))

token_type, token_id = cursor.fetchone()

console.print("token_type:", token_type)
console.print("token_id:", token_id)


env_vars = dotenv_values(f"{project_root}/.env")

salt = env_vars["API_TOKEN_SALT"]
key = os.urandom(128).hex()
hashed = hash(salt, key)

cursor.execute(
    "UPDATE strapi_api_tokens SET access_key = ? WHERE name = ?",
    (hashed, token_name),
)

conn.commit()

cursor.execute(
    "SELECT api_token_permission_id FROM strapi_api_token_permissions_token_lnk WHERE api_token_id = ?",
    (token_id,),
)

permission_ids = []

for row in cursor.fetchall():
    permission_ids.append(row[0])

cursor.execute(
    "SELECT action FROM strapi_api_token_permissions WHERE id IN ({})".format(
        ",".join("?" for _ in permission_ids)
    ),
    permission_ids,
)

permission_actions = {}

for row in cursor.fetchall():
    if row[0].startswith("api::"):
        scope, api, action = row[0].split(".")
        if not permission_actions.get(api):
            permission_actions[api] = []
        permission_actions[api].append(action)

content_types = {}

for api in permission_actions:
    with open(
        f"{project_root}/src/api/{api}/content-types/{api}/schema.json",
        "r",
        encoding="utf-8",
    ) as f:
        content_types[api] = json.loads(f.read())
        content_types[api]["actions"] = permission_actions[api]
        content_types[api]["url"] = (
            project_origin + "/api/" + content_types[api]["info"]["pluralName"]
        )

console.print("content types:", content_types)
console.print("token:", key)

conn.close()
