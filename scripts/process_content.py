"""Content automation pipeline script (Direct API Version).

This script uses direct HTTP requests to Notion to avoid SDK version conflicts.
"""
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

# --- NUEVA LÓGICA NOTION SIN LIBRERÍA ---

def get_notion_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json"
    }

def notion_extract_text(prop: Dict) -> str:
    # Extrae texto plano de propiedades Rich Text o Title
    if not prop: return ""
    # A veces viene como lista directa o dentro de un objeto
    items = prop.get("rich_text", []) if "rich_text" in prop else prop.get("title", [])
    return "".join([t.get("plain_text", "") for t in items]).strip()

def notion_extract_select(prop: Dict) -> str:
    # Extrae texto de propiedades Select
    if not prop: return ""
    return prop.get("select", {}).get("name", "") if prop.get("select") else ""

def fetch_ready_pages() -> List[LessonEntry]:
    print(f"📡 Conectando a Notion (API Directa)... ID: {NOTION_DATABASE_ID}")
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    
    payload = {
        "filter": {
            "property": "Status",
            "status": {"equals": "Ready to Process"} # Ojo: "status" para propiedad tipo Status
        }
    }
    
    response = requests.post(url, json=payload, headers=get_notion_headers())
    
    if response.status_code != 200:
        raise Exception(f"Error Notion {response.status_code}: {response.text}")
        
    data = response.json()
    results = data.get("results", [])
    print(f"✅ Encontrados {len(results)} registros.")
    
    entries = []
    for page in results:
        props = page.get("properties", {})
        
        # Extracción manual segura
        theme = notion_extract_text(props.get("Tema", {})) or "Sin Título"
        raw_content = notion_extract_text(props.get("Raw Content", {}))
        unit = notion_extract_select(props.get("Unidad", {}))
        action_type = notion_extract_select(props.get("Action Type", {})) or "Create Lesson"
        
        slug_value = slugify(theme)
        
        entries.append(LessonEntry(
            page_id=page["id"],
            theme=theme,
            raw_content=raw_content,
            unit=unit,
            action_type=action_type,
            slug=slug_value
        ))
        
    return entries

def update_notion_status(page_ids: List[str]) -> None:
    print(f"🔄 Actualizando estado de {len(page_ids)} páginas en Notion...")
    headers = get_notion_headers()
    
    for page_id in page_ids:
        url = f"https://api.notion.com/v1/pages/{page_id}"
        # Payload para propiedad tipo Status (Kanban nativo de Notion)
        payload = {
            "properties": {
                "Status": {
                    "status": {"name": "In Review"}
                }
            }
        }
        res = requests.patch(url, json=payload, headers=headers)
        if res.status_code != 200:
            print(f"⚠️ Error actualizando página {page_id}: {res.text}")

# --- RESTO DEL SCRIPT IGUAL ---

def generate_markdown_content(client: OpenAI, entry: LessonEntry, unit_label: Optional[str] = None) -> str:
    unit_header = unit_label or entry.unit
    
    if entry.action_type == "Add Exercises":
        system_prompt = "Eres un experto creador de ejercicios de español (ELE). Crea práctica interactiva con soluciones ocultas."
        user_prompt = (
            f"Contexto: Unidad {unit_header} - Tema: {entry.theme}\nNotas: {entry.raw_content}\n\n"
            "Crea 5-10 ejercicios variados (Test, Huecos).\n"
            "FORMATO: Usa H3 (###). Oculta soluciones así: <details><summary>Solución</summary>RESPUESTA</details>"
        )
    else:
        system_prompt = "Eres un profesor de español experto. Crea lecciones explicativas ricas y claras para angloparlantes."
        user_prompt = (
            f"Unidad: {unit_header}\nTema: {entry.theme}\nBase: {entry.raw_content}\n\n"
            "Escribe la lección en Markdown. Usa tablas para vocabulario. Explica en inglés, ejemplos en español."
            "NO uses frontmatter."
        )

    completion = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
    )
    body = completion.choices[0].message.content.strip()

    if entry.action_type == "Add Exercises":
        return body

    return f"---\ntitle: \"{entry.theme}\"\nunit: \"{unit_header}\"\nslug: \"{entry.slug}\"\n---\n\n{body}\n"

def build_unit_zero_content(client: OpenAI, entries: List[LessonEntry]) -> str:
    sections = []
    print(f"📦 Procesando Unidad 0 ({len(entries)} partes)...")
    for entry in entries:
        print(f"  > Generando: {entry.theme}")
        full = generate_markdown_content(client, entry, unit_label="Unidad 0")
        body = full if entry.action_type == "Add Exercises" else full.split("---", 2)[-1].strip()
        sections.append(f"## {entry.theme}\n\n{body}")

    front = "---\ntitle: \"Unidad 0: Introducción\"\nunit: \"Unidad 0\"\nslug: \"unidad-0-intro\"\n---\n\n"
    intro = "Bienvenido a la Unidad 0. Fundamentos del español.\n\n"
    joined = "\n\n---\n\n".join(sections)
    return f"{front}{intro}{joined}\n"

def git_ops(repo, pr_title, pr_body):
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
    subprocess.run(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"], check=True)
    
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    branch = f"content-update-{timestamp}"
    
    subprocess.run(["git", "checkout", "-b", branch], check=True)
    subprocess.run(["git", "add", "."], check=True)
    subprocess.run(["git", "commit", "-m", pr_title], check=True)
    subprocess.run(["git", "push", "origin", branch], check=True)
    
    repo.create_pull(title=pr_title, body=pr_body, head=branch, base="main")
    print(f"✅ PR Creado: {branch}")

def main():
    ensure_environment()
    
    # Github Init
    auth = Auth.Token(GITHUB_TOKEN)
    github = Github(auth=auth)
    repo = github.get_repo(GITHUB_REPOSITORY)
    openai_client = OpenAI(api_key=OPENAI_API_KEY)

    try:
        entries = fetch_ready_pages()
    except Exception as e:
        print(f"❌ Error fatal conectando a Notion: {e}")
        return

    if not entries:
        print("📭 No hay contenido listo (Ready to Process).")
        return

    CONTENT_DIR.mkdir(parents=True, exist_ok=True)
    
    unit_0 = [e for e in entries if "unidad 0" in e.unit.lower()]
    others = [e for e in entries if "unidad 0" not in e.unit.lower()]
    processed = []

    if unit_0:
        content = build_unit_zero_content(openai_client, unit_0)
        (CONTENT_DIR / "unidad-0.md").write_text(content, encoding="utf-8")
        processed.extend([e.page_id for e in unit_0])

    for entry in others:
        print(f"📝 Generando: {entry.theme}")
        content = generate_markdown_content(openai_client, entry)
        path = CONTENT_DIR / f"{entry.slug}.md"
        
        if entry.action_type == "Add Exercises" and path.exists():
            with path.open("a", encoding="utf-8") as f:
                f.write(f"\n\n---\n\n### 🏋️ Práctica\n\n{content}")
        else:
            path.write_text(content, encoding="utf-8")
        processed.append(entry.page_id)

    if processed:
        update_notion_status(processed)

    if subprocess.check_output(["git", "status", "--porcelain"]).strip():
        git_ops(repo, "Automated Content Update", "Generated by AI pipeline (Direct API).")
    else:
        print("🤷‍♂️ No hay cambios en los archivos.")

if __name__ == "__main__":
    main()
