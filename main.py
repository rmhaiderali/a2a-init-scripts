import os
import re
import json
import hmac
import hashlib
import sqlite3
from jinja2 import Template
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

# \"\"\"
# {{ docstring }}
# \"\"\"

function_template = Template(
    f"""

{
    "async def {{ name }}"
    "("
    "{% for arg in args %}"
    "{{ arg.name }}{% if arg.suffix %}{{ arg.suffix }}{% endif %}: {{ arg.type }}"
    "{% if is_first_optional or not loop.first %}"
    "{% if arg.default %} = {{ arg.default }}{% else %} = None{% endif %}"
    "{% endif %}"
    "{% if not loop.last %}, {% endif %}"
    "{% endfor %}"
    ")"
    "{% if return_type %} -> {{ return_type }}{% endif %}:"
    "\n    {{ body|indent(4) }}"
}

"""
)

file = f"""
import json
import requests
from typing import Literal
from rich.console import Console

console = Console()

headers = {{
    "Authorization": "Bearer {key}",
    "Content-Type": "application/json"
}}
"""

functions = ""
function_names = []

for content_type in content_types.values():
    for action in content_type["actions"]:
        singular_name = content_type["info"]["singularName"]
        plural_name = content_type["info"]["pluralName"]

        simple_action = {
            "find": "find_all",
            "findOne": "find",
            "create": "create",
            "update": "update",
            "delete": "delete",
        }[action]

        args = []

        if simple_action in ["find", "update", "delete"]:
            args.append(
                {
                    "name": singular_name,
                    "type": "str",
                    "suffix": "_id",
                    "is_not_payload": True,
                }
            )

        if simple_action in ["create", "update"]:
            for field in content_type["attributes"]:
                if content_type["attributes"][field]["type"] == "integer":
                    args.append({"name": field, "type": "int | None"})
                elif content_type["attributes"][field]["type"] == "string":
                    args.append({"name": field, "type": "str | None"})
                elif content_type["attributes"][field]["type"] == "boolean":
                    args.append({"name": field, "type": "bool | None"})
                elif content_type["attributes"][field]["type"] == "enumeration":
                    values = content_type["attributes"][field]["enum"]
                    args.append(
                        {"name": field, "type": f"Literal{json.dumps(values)} | None"}
                    )
                elif content_type["attributes"][field]["type"] == "relation":
                    single = content_type["attributes"][field]["relation"].endswith(
                        "One"
                    )
                    id_or_ids = "_id" if single else "_ids"
                    args.append(
                        {
                            "name": field,
                            "type": f"{'str' if single else 'list[str]'} | None",
                            "suffix": id_or_ids,
                            "is_relation": True,
                            "is_single": single,
                        }
                    )
                    if simple_action == "update":
                        args.append(
                            {
                                "name": field,
                                "type": 'Literal["add", "remove"] | None',
                                "suffix": f"{id_or_ids}_action",
                                "is_action": True,
                            }
                        )
                else:
                    args.append({"name": field, "type": "str | None"})

        if action == "find":
            body = f"""
                url = f"{project_origin}/api/{plural_name}"
                return requests.request("GET", url, headers=headers).json()
            """

        elif action == "findOne":
            body = f"""
                url = f"{project_origin}/api/{plural_name}/{{{singular_name}_id}}"
                return requests.request("GET", url, headers=headers).json()
            """

        elif action == "create":
            data = ", ".join(
                [
                    (
                        f'"{arg["name"]}": None if {var_name} is None else {{ '
                        f'"connect": '
                        f'{"[" if is_single else ""}{var_name}{"]" if is_single else ""} }}'
                        if arg.get("is_relation", False)
                        else f'"{arg["name"]}": {var_name}'
                    )
                    for arg in args
                    if not arg.get("is_action", False)
                    and not arg.get("is_not_payload", False)
                    for var_name, is_single in [
                        (
                            f'{arg["name"]}{arg.get("suffix", "")}',
                            arg.get("is_single", False),
                        )
                    ]
                ]
            )
            body = f"""
                data = {{{data}}}
                data = {{k: v for k, v in data.items() if v is not None}}
                url = f"{project_origin}/api/{plural_name}"
                return requests.request("POST", url, headers=headers, data=json.dumps({{"data": data}})).json()
            """

        elif action == "update":
            data = ", ".join(
                [
                    (
                        f'"{arg["name"]}": None if {var_name}_action is None or {var_name} is None else {{ '
                        f'("connect" if {var_name}_action == "add" else "disconnect"): '
                        f'{"[" if is_single else ""}{var_name}{"]" if is_single else ""} }}'
                        if arg.get("is_relation", False)
                        else f'"{arg["name"]}": {var_name}'
                    )
                    for arg in args
                    if not arg.get("is_action", False)
                    and not arg.get("is_not_payload", False)
                    for var_name, is_single in [
                        (
                            f'{arg["name"]}{arg.get("suffix", "")}',
                            arg.get("is_single", False),
                        )
                    ]
                ]
            )
            body = f"""
                data = {{{data}}}
                data = {{k: v for k, v in data.items() if v is not None}}
                url = f"{project_origin}/api/{plural_name}/{{{singular_name}_id}}"
                return requests.request("PUT", url, headers=headers, data=json.dumps({{"data": data}})).json()
            """

        elif action == "delete":
            body = f"""
                url = f"{project_origin}/api/{plural_name}/{{{singular_name}_id}}"
                return requests.request("DELETE", url, headers=headers).json()
            """

        else:
            body = f"""
                return {{error: "No implementation for this action yet"}}
            """

        function_name = f"{simple_action}_{plural_name if simple_action.endswith("all") else singular_name}"
        function_names.append(function_name)

        functions += function_template.render(
            **{
                "is_first_optional": simple_action in ["create", "find_all"],
                "name": function_name,
                "args": args,
                "returns": "dict",
                "body": re.sub(r"^ {16}", "", body.strip(), flags=re.MULTILINE),
            }
        )

with open("generated_functions.py", "w") as f:
    f.write(file + functions + f"\ntools = [{", ".join(function_names)}]\n")

# console.print(find_service("tvyt9r24jtt9qwk55hrg93yf"))
