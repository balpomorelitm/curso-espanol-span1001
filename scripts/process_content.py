"""Content automation pipeline script (Individual Files Version)."""
from __future__ import annotations

import os
import subprocess
import requests
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from openai import OpenAI
from slugify import slugify
from github import Github, Auth

# Configuración
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
NOTION_VERSION = "2022-06-28"

CONTENT_DIR = Path("src/content/lessons")

@dataclass
class LessonEntry:
    page_id: str
    theme: str
    raw_content: str
    unit: str
    action_type: str
    slug: str

def ensure_environment() -> None:
    missing = [k for k, v in {
        "NOTION_TOKEN": NOTION_TOKEN,
        "NOTION_DATABASE_ID": NOTION_DATABASE_ID,
        "OPENAI_API_KEY": OPENAI_API_KEY,
        "GITHUB_TOKEN": GITHUB_TOKEN,
        "GITHUB_REPOSITORY": GITHUB_REPOSITORY
    }.items() if not v]
    if missing:
        raise EnvironmentError(f"Missing env vars: {', '.join(missing)}")

def get_notion_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json"
    }

def notion_extract_text(prop: Dict) -> str:
    if not prop: return ""
    items = prop.get("rich_text", []) if "rich_text" in prop else prop.get("title", [])
    return "".join([t.get("plain_text", "") for t in items]).strip()

def notion_extract_select(prop: Dict) -> str:
    if not prop: return ""
    return prop.get("select", {}).get("name", "") if prop.get("select") else ""

def fetch_ready_pages() -> List[LessonEntry]:
    print(f"📡 Conectando a Notion... ID: {NOTION_DATABASE_ID}")
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    payload = {
        "filter": {
            "property": "Status",
            "status": {"equals": "Ready to Process"}
        }
    }
    response = requests.post(url, json=payload, headers=get_notion_headers())
    if response.status_code != 200:
        raise Exception(f"Error Notion {response.status_code}: {response.text}")
        
    results = response.json().get("results", [])
    print(f"✅ Encontrados {len(results)} registros.")
    
    entries = []
    for page in results:
        props = page.get("properties", {})
        theme = notion_extract_text(props.get("Tema", {})) or "Sin Título"
        raw_content = notion_extract_text(props.get("Raw Content", {}))
        unit = notion_extract_select(props.get("Unidad", {}))
        action_type = notion_extract_select(props.get("Action Type", {})) or "Create Lesson"
        slug_value = slugify(theme)
        
        entries.append(LessonEntry(
            page_id=page["id"], theme=theme, raw_content=raw_content,
            unit=unit, action_type=action_type, slug=slug_value
        ))
    return entries

def update_notion_status(page_ids: List[str]) -> None:
    print(f"🔄 Actualizando estado de {len(page_ids)} páginas...")
    headers = get_notion_headers()
    for page_id in page_ids:
        url = f"https://api.notion.com/v1/pages/{page_id}"
        requests.patch(url, json={"properties": {"Status": {"status": {"name": "In Review"}}}}, headers=headers)

def generate_markdown_content(client: OpenAI, entry: LessonEntry) -> str:
    # Prompt mejorado para ejercicios interactivos
    if entry.action_type == "Add Exercises":
        system_prompt = (
            "Eres un experto en didáctica de lenguas. Creas ejercicios para una web interactiva. "
            "IMPORTANTE: Genera ejercicios usando el formato específico para el script de autocorrección."
        )
        user_prompt = (
            f"Tema: {entry.theme}\nContenido: {entry.raw_content}\n\n"
            "Crea 5 preguntas variadas (huecos, traducción, elección).\n"
            "FORMATO OBLIGATORIO PARA CADA PREGUNTA:\n"
            "1. Escribe la pregunta/instrucción clara en Negrita.\n"
            "2. Inmediatamente debajo, pon la solución dentro de <details><summary>Solución</summary>TU_RESPUESTA_AQUI</details>\n"
            "3. La respuesta dentro de details debe ser SOLO la palabra o frase correcta, sin explicaciones extra dentro del tag.\n"
            "Ejemplo:\n"
            "**Traduce 'House':**\n"
            "<details><summary>Solución</summary>Casa</details>\n\n"
        )
    else:
        system_prompt = "Eres un profesor de español experto. Creas lecciones web divididas en secciones cortas y claras."
        user_prompt = (
            f"Unidad: {entry.unit}\nTema: {entry.theme}\nNotas: {entry.raw_content}\n\n"
            "Escribe una lección en Markdown muy estructurada.\n"
            "- Usa subtítulos (##) frecuentes para romper el texto.\n"
            "- Usa tablas para vocabulario.\n"
            "- Mantén los párrafos cortos.\n"
            "NO incluyas frontmatter."
        )

    completion = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
    )
    return completion.choices[0].message.content.strip()

def git_ops(repo, pr_title, pr_body):
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
    subprocess.run(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"], check=True)
    branch = f"content-update-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    subprocess.run(["git", "checkout", "-b", branch], check=True)
    subprocess.run(["git", "add", "."], check=True)
    subprocess.run(["git", "commit", "-m", pr_title], check=True)
    try:
        subprocess.run(["git", "push", "origin", branch], check=True)
        repo.create_pull(title=pr_title, body=pr_body, head=branch, base="main")
        print(f"✅ PR Creado: {branch}")
    except Exception as e:
        print(f"⚠️ Error Git: {e}")

def main():
    ensure_environment()
    auth = Auth.Token(GITHUB_TOKEN)
    repo = Github(auth=auth).get_repo(GITHUB_REPOSITORY)
    client = OpenAI(api_key=OPENAI_API_KEY)

    try: entries = fetch_ready_pages()
    except Exception as e: return print(f"❌ Error Notion: {e}")

    if not entries: return print("📭 Nada nuevo.")

    CONTENT_DIR.mkdir(parents=True, exist_ok=True)
    processed = []

    for entry in entries:
        print(f"📝 Procesando: {entry.theme}")
        content = generate_markdown_content(client, entry)
        path = CONTENT_DIR / f"{entry.slug}.md"
        
        if entry.action_type == "Add Exercises" and path.exists():
            with path.open("a", encoding="utf-8") as f:
                f.write(f"\n\n---\n\n## 🏋️ Práctica Interactiva\n\n{content}")
        else:
            frontmatter = f"---\ntitle: \"{entry.theme}\"\nunit: \"{entry.unit}\"\nslug: \"{entry.slug}\"\n---\n\n"
            path.write_text(frontmatter + content, encoding="utf-8")
        
        processed.append(entry.page_id)

    if processed: update_notion_status(processed)
    
    if subprocess.check_output(["git", "status", "--porcelain"]).strip():
        git_ops(repo, "New Content (Split Lessons)", "Generated individual lessons + Interactive exercises.")

if __name__ == "__main__":
    main()
