"""Content automation pipeline script (Text Only).

This script fetches ready-to-process rows from Notion, generates enriched
lesson markdown via GPT (configurable model), and opens an automated pull request.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from notion_client import Client as NotionClient
from openai import OpenAI
from slugify import slugify
from github import Github

# Configuración de entorno
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

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
    missing = [
        name
        for name, value in {
            "NOTION_TOKEN": NOTION_TOKEN,
            "NOTION_DATABASE_ID": NOTION_DATABASE_ID,
            "OPENAI_API_KEY": OPENAI_API_KEY,
            "GITHUB_TOKEN": GITHUB_TOKEN,
            "GITHUB_REPOSITORY": GITHUB_REPOSITORY,
        }.items()
        if not value
    ]
    if missing:
        raise EnvironmentError(f"Missing required environment variables: {', '.join(missing)}")


def notion_rich_text_value(properties: Dict, field: str) -> str:
    texts = properties.get(field, {}).get("rich_text", [])
    return "".join(part.get("plain_text", "") for part in texts).strip()


def notion_select_value(properties: Dict, field: str) -> str:
    return properties.get(field, {}).get("select", {}).get("name", "")


def fetch_ready_pages(notion: NotionClient) -> List[LessonEntry]:
    response = notion.databases.query(
        **{
            "database_id": NOTION_DATABASE_ID,
            "filter": {
                "property": "Status",
                "select": {"equals": "Ready to Process"},
            },
        }
    )
    entries: List[LessonEntry] = []
    for result in response.get("results", []):
        properties = result.get("properties", {})
        
        theme_prop = properties.get("Tema", {}).get("title", [])
        theme = "".join([t.get("plain_text", "") for t in theme_prop]) if theme_prop else "Sin Título"
        
        raw_content = notion_rich_text_value(properties, "Raw Content")
        unit = notion_select_value(properties, "Unidad")
        action_type = notion_select_value(properties, "Action Type") or "Create Lesson"
        
        slug_value = slugify(theme or "lesson")
        
        entries.append(
            LessonEntry(
                page_id=result.get("id", ""),
                theme=theme,
                raw_content=raw_content,
                unit=unit,
                action_type=action_type,
                slug=slug_value,
            )
        )
    return entries


def generate_markdown_content(
    client: OpenAI, entry: LessonEntry, unit_label: Optional[str] = None
) -> str:
    unit_header = unit_label or entry.unit
    
    if entry.action_type == "Add Exercises":
        system_prompt = (
            "Eres un creador experto de materiales didácticos de español (ELE). "
            "Tu objetivo es crear baterías de ejercicios prácticos que permitan al alumno autoevaluarse."
        )
        user_prompt = (
            f"Contexto: Unidad {unit_header} - Tema: {entry.theme}\n"
            f"Notas del tema: {entry.raw_content}\n\n"
            "Genera una batería de 5 a 10 ejercicios siguiendo esta progresión:\n"
            "1. RECONOCIMIENTO (Selección múltiple / Verdadero o Falso).\n"
            "2. PRÁCTICA (Rellenar huecos / Relacionar).\n"
            "3. PRODUCCIÓN (Traducir o completar frases).\n\n"
            "REGLAS CRÍTICAS DE FORMATO:\n"
            "- Usa H3 (###) para titular cada bloque de ejercicios.\n"
            "- IMPORTANTE: Debes incluir la solución y una breve explicación del error común.\n"
            "- Oculta la solución usando el tag <details> de HTML para que sea interactivo.\n\n"
            "Ejemplo de formato requerido:\n"
            "**1. Traduce: 'Good morning'**\n"
            "<details>\n"
            "<summary>Ver Solución</summary>\n"
            "\n"
            "**Buenos días**\n"
            "> Nota: Se usa hasta el mediodía.\n"
            "</details>\n"
        )
    else:
        system_prompt = (
            "Eres un profesor de español de talla mundial, experto en enseñar a angloparlantes. "
            "Tu objetivo es convertir notas esquemáticas en lecciones ricas, explicativas y amigables.\n\n"
            "REGLAS DE ORO:\n"
            "1. EXPANSIÓN CREATIVA: Rellena los huecos. Explica el contexto cultural y pronunciación.\n"
            "2. ESTRUCTURA: Introducción breve, cuerpo de la lección y resumen.\n"
            "3. EJEMPLOS: Proporciona 3 ejemplos prácticos con traducción al inglés por cada regla.\n"
            "4. FORMATO: Usa tablas Markdown para vocabulario. Negritas para conceptos clave.\n"
            "5. IDIOMA: Explica en inglés, ejemplos en español.\n"
            "6. ALCANCE: Empieza con presente simple y verbos regulares si no se especifica otra cosa."
        )
        user_prompt = (
            f"Unidad: {unit_header}\n"
            f"Tema: {entry.theme}\n"
            f"Contenido base:\n{entry.raw_content}\n\n"
            "Genera una lección en Markdown. NO incluyas frontmatter (---) ni títulos H1 (#)."
        )

    completion = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    body = completion.choices[0].message.content.strip()

    if entry.action_type == "Add Exercises":
        return body

    frontmatter_lines = [
        "---",
        f"title: \"{entry.theme}\"",
        f"unit: \"{unit_header}\"",
        f"slug: \"{entry.slug}\"",
        "---",
        "",
    ]
    frontmatter = "\n".join(frontmatter_lines)
    return f"{frontmatter}{body}\n"


def update_notion_status(notion: NotionClient, page_ids: List[str]) -> None:
    for page_id in page_ids:
        notion.pages.update(page_id=page_id, properties={"Status": {"status": {"name": "In Review"}}})


def git_has_changes() -> bool:
    result = subprocess.check_output(["git", "status", "--porcelain"])
    return bool(result.strip())


def git_run(args: List[str]) -> None:
    subprocess.run(args, check=True)


def create_branch_and_pr(repo, branch_name: str, pr_title: str, pr_body: str) -> None:
    git_run(["git", "checkout", "-b", branch_name])
    git_run(["git", "add", "."])
    git_run(["git", "commit", "-m", pr_title])
    git_run(["git", "push", "origin", branch_name])
    repo.create_pull(title=pr_title, body=pr_body, head=branch_name, base="main")


def build_unit_zero_content(
    client: OpenAI, entries: List[LessonEntry]
) -> str:
    sections = []
    print(f"Procesando {len(entries)} entradas para Unidad 0...")
    
    for entry in entries:
        print(f"  > Generando: {entry.theme}")
        content_full = generate_markdown_content(client, entry, unit_label="Unidad 0")
        
        if entry.action_type == "Add Exercises":
             body = content_full
        else:
             body = content_full.split("---", 2)[-1].strip()
             
        sections.append(f"## {entry.theme}\n\n{body}")

    frontmatter = "\n".join(
        [
            "---",
            "title: \"Unidad 0: Introducción\"",
            "unit: \"Unidad 0\"",
            "slug: \"unidad-0-intro\"",
            "---",
            "",
        ]
    )
    intro_text = "Bienvenido a la Unidad 0. Aquí están los fundamentos.\n\n"
    
    # CORRECCIÓN AQUÍ: Sacamos la unión fuera del f-string para evitar el SyntaxError
    separator = "\n\n---\n\n"
    joined_sections = separator.join(sections)
    
    return f"{frontmatter}{intro_text}{joined_sections}\n"


def main() -> None:
    ensure_environment()

    notion = NotionClient(auth=NOTION_TOKEN)
    openai_client = OpenAI(api_key=OPENAI_API_KEY)
    github = Github(GITHUB_TOKEN)
    repo = github.get_repo(GITHUB_REPOSITORY)

    print("--- Consultando Notion ---")
    entries = fetch_ready_pages(notion)
    if not entries:
        print("No ready entries found.")
        return

    CONTENT_DIR.mkdir(parents=True, exist_ok=True)

    unit_zero_entries = [e for e in entries if "unidad 0" in e.unit.lower()]
    other_entries = [e for e in entries if "unidad 0" not in e.unit.lower()]

    processed_pages: List[str] = []

    if unit_zero_entries:
        print("Generando archivo agrupado para Unidad 0...")
        unit_zero_content = build_unit_zero_content(openai_client, unit_zero_entries)
        output_file = CONTENT_DIR / "unidad-0.md"
        output_file.write_text(unit_zero_content, encoding="utf-8")
        processed_pages.extend([entry.page_id for entry in unit_zero_entries])

    for entry in other_entries:
        print(f"Generando lección individual: {entry.theme}")
        content = generate_markdown_content(openai_client, entry)
        output_file = CONTENT_DIR / f"{entry.slug}.md"
        
        if entry.action_type == "Add Exercises" and output_file.exists():
            print(f"  -> Añadiendo ejercicios al final de {entry.slug}.md")
            with output_file.open("a", encoding="utf-8") as f:
                f.write("\n\n---\n\n### 🏋️ Práctica / Exercises\n\n")
                f.write(content)
        else:
            output_file.write_text(content, encoding="utf-8")
            
        processed_pages.append(entry.page_id)

    if processed_pages:
        update_notion_status(notion, processed_pages)

    if not git_has_changes():
        print("No changes detected after processing.")
        return

    git_run(["git", "config", "user.name", "github-actions[bot]"])
    git_run(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"])

    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    branch_name = f"content-update-{timestamp}"
    pr_title = "Automated content update"
    pr_body = "This PR adds generated lesson content and exercises."

    try:
        create_branch_and_pr(repo, branch_name, pr_title, pr_body)
        print(f"Created pull request on branch {branch_name}.")
    except Exception as e:
        print(f"Error creating PR: {e}")

if __name__ == "__main__":
    main()
