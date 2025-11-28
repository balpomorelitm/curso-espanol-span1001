"""Content automation pipeline script.

This script fetches ready-to-process rows from Notion, generates enriched
lesson markdown via GPT-4o, creates supporting DALL·E 3 artwork, and opens
an automated pull request with the changes.
"""
from __future__ import annotations

import base64
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from notion_client import Client as NotionClient
from openai import OpenAI
from PIL import Image
from slugify import slugify
from github import Github


NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY")

CONTENT_DIR = Path("src/content/lessons")
IMAGES_DIR = Path("public/images")


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
        theme = notion_rich_text_value(properties, "Theme")
        raw_content = notion_rich_text_value(properties, "Raw Content")
        unit = notion_select_value(properties, "Unit")
        action_type = notion_select_value(properties, "Action Type") or "Create"
        slug_source = notion_rich_text_value(properties, "Slug") or theme
        slug_value = slugify(slug_source or "lesson")
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
    client: OpenAI, entry: LessonEntry, image_path: Path, unit_label: Optional[str] = None
) -> str:
    unit_header = unit_label or entry.unit
    system_prompt = (
        "Eres un generador de lecciones de español. Usa el contenido provisto como base, "
        "expande las explicaciones, agrega ejemplos prácticos y traduce términos clave al inglés. "
        "Devuelve el cuerpo en Markdown listo para Astro content collections."
    )
    user_prompt = (
        f"Unidad: {unit_header}\n"
        f"Tema: {entry.theme}\n"
        f"Acción: {entry.action_type}\n"
        "Contenido base:\n"
        f"{entry.raw_content}\n\n"
        "Genera una sección en Markdown con un tono educativo, encabezados claros y una lista de ejemplos."
    )
    completion = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    body = completion.choices[0].message.content.strip()
    image_web_path = web_image_path(image_path)

    frontmatter_lines = [
        "---",
        f"title: \"{entry.theme}\"",
        f"unit: \"{unit_header}\"",
        f"slug: \"{entry.slug}\"",
        f"image: \"/{image_web_path}\"",
        "---",
        "",
    ]
    frontmatter = "\n".join(frontmatter_lines)
    image_section = f"![Ilustración de la lección](/" + image_web_path + ")\n\n"
    return f"{frontmatter}{image_section}{body}\n"


def generate_image(client: OpenAI, prompt: str, output_path: Path) -> None:
    response = client.images.generate(
        model="dall-e-3",
        prompt=prompt,
        size="1024x1024",
        n=1,
    )
    b64_data = response.data[0].b64_json
    image_bytes = base64.b64decode(b64_data)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(image_bytes)
    # Validate image
    with Image.open(output_path) as img:
        img.verify()


def update_notion_status(notion: NotionClient, page_ids: List[str]) -> None:
    for page_id in page_ids:
        notion.pages.update(page_id=page_id, properties={"Status": {"select": {"name": "In Review"}}})


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
    client: OpenAI, entries: List[LessonEntry], image_path: Path
) -> str:
    sections = []
    for entry in entries:
        content = generate_markdown_content(client, entry, image_path, unit_label="Unidad 0")
        # Drop frontmatter for aggregated sections
        body = content.split("---", 2)[-1].strip()
        sections.append(f"## {entry.theme}\n\n{body}")

    image_web_path = web_image_path(image_path)
    frontmatter = "\n".join(
        [
            "---",
            "title: \"Unidad 0: Introducción\"",
            "unit: \"Unidad 0\"",
            "slug: \"unidad-0-intro\"",
            f"image: \"/{image_web_path}\"",
            "---",
            "",
        ]
    )
    header_image = f"![Ilustración de la introducción](/" + image_web_path + ")\n\n"
    return f"{frontmatter}{header_image}{'\n\n'.join(sections)}\n"


def web_image_path(path: Path) -> str:
    raw = str(path).replace(os.sep, "/")
    if raw.startswith("public/"):
        return raw[len("public/") :]
    return raw


def main() -> None:
    ensure_environment()

    notion = NotionClient(auth=NOTION_TOKEN)
    openai_client = OpenAI(api_key=OPENAI_API_KEY)
    github = Github(GITHUB_TOKEN)
    repo = github.get_repo(GITHUB_REPOSITORY)

    entries = fetch_ready_pages(notion)
    if not entries:
        print("No ready entries found.")
        return

    CONTENT_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    unit_zero_entries = [e for e in entries if e.unit.lower() == "unidad 0"]
    other_entries = [e for e in entries if e.unit.lower() != "unidad 0"]

    processed_pages: List[str] = []

    if unit_zero_entries:
        image_path = IMAGES_DIR / "unidad-0-intro.png"
        generate_image(
            openai_client,
            "Vibrant classroom scene introducing Spanish basics with welcoming visuals.",
            image_path,
        )
        unit_zero_content = build_unit_zero_content(openai_client, unit_zero_entries, image_path)
        output_file = CONTENT_DIR / "unidad-0-intro.md"
        output_file.write_text(unit_zero_content, encoding="utf-8")
        processed_pages.extend([entry.page_id for entry in unit_zero_entries])

    for entry in other_entries:
        image_path = IMAGES_DIR / f"{entry.slug}.png"
        generate_image(
            openai_client,
            f"Educational illustration for Spanish lesson about {entry.theme} with cultural elements.",
            image_path,
        )
        content = generate_markdown_content(openai_client, entry, image_path)
        output_file = CONTENT_DIR / f"{entry.slug}.md"
        if entry.action_type.lower() == "add exercises" and output_file.exists():
            extra_body = content.split("---", 2)[-1].strip()
            with output_file.open("a", encoding="utf-8") as f:
                f.write("\n\n### Ejercicios adicionales\n\n")
                f.write(extra_body)
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
    pr_body = "This PR adds generated lesson content and images from the content pipeline."

    create_branch_and_pr(repo, branch_name, pr_title, pr_body)
    print(f"Created pull request on branch {branch_name}.")


if __name__ == "__main__":
    main()
