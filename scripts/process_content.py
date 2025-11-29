def generate_markdown_content(client: OpenAI, entry: LessonEntry) -> str:
    # --- MODO 1: ENTRENADOR DINÁMICO (3 EJERCICIOS VARIADOS) ---
    if entry.action_type == "Add Exercises":
        system_prompt = (
            "You are an expert educational software architect for Spanish (ELE). "
            "Your goal is to generate structured DATA for A SET OF 3 VARIED interactive exercises. "
            "Output ONLY valid JSON."
        )
        user_prompt = (
            f"Topic: {entry.theme}\nContent Notes: {entry.raw_content}\n\n"
            "Create a list of 3 DISTINCT interactive exercises adapted to this topic.\n"
            "Choose the best mix from these types (do not always use the same ones!):\n"
            "1. 'fill_gaps' (Grammar/Conjugation/Context)\n"
            "2. 'matching' (Definitions/Collocations)\n"
            "3. 'flashcards' (Vocabulary/Memorization)\n"
            "4. 'multiple_choice' (Reading Comprehension/Quizzes)\n\n"
            "REQUIREMENTS:\n"
            "- If it's a Reading/Context topic -> Use 'multiple_choice' or 'fill_gaps'.\n"
            "- If it's Vocabulary -> Use 'flashcards' or 'matching'.\n"
            "- 'set_a': 6-10 items per exercise.\n"
            "- 'set_b': 6-10 EXTRA items for regeneration.\n\n"
            "JSON STRUCTURE:\n"
            "[\n"
            "  {\n"
            "    \"type\": \"multiple_choice\",\n"
            "    \"title\": \"Comprensión Lectora\",\n"
            "    \"instruction\": \"Lee y elige la opción correcta.\",\n"
            "    \"set_a\": [\n"
            "       {\"q\": \"Question text?\", \"options\": [\"Wrong\", \"Correct\", \"Wrong\"], \"a\": \"Correct\"}\n"
            "    ],\n"
            "    \"set_b\": [...]\n"
            "  },\n"
            "  { \"type\": \"matching\", ... },\n"
            "  { \"type\": \"fill_gaps\", ... }\n"
            "]\n"
            "Output ONLY the JSON list."
        )

        completion = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        )
        
        content = completion.choices[0].message.content.strip()
        if content.startswith("```json"): content = content.replace("```json", "").replace("```", "")
        
        try:
            exercises = json.loads(content)
            markdown_output = "\n\n---\n\n## 🏋️ Práctica / Exercises\n"
            for i, ex in enumerate(exercises, 1):
                markdown_output += f"\n### {i}. {ex['title']}\n"
                markdown_output += f"<div class='exercise-data' style='display:none;'>{json.dumps(ex)}</div>\n"
            return markdown_output
            
        except json.JSONDecodeError:
            return "\n\n> Error generando ejercicios."

    # --- MODO 2: PROFESOR ESTRELLA (TEORÍA) ---
    else:
        # (El resto del código para teoría se mantiene igual que antes...)
        system_prompt = (
            "You are a world-class Spanish as a Foreign Language (ELE) teacher. "
            "Your teaching style is fun, engaging, and highly visual (using emojis). 🚀 "
            "You specialize in explaining Spanish concepts to English and Chinese speakers."
        )
        user_prompt = (
            f"Unit: {entry.unit}\nTopic: {entry.theme}\nRaw Notes: {entry.raw_content}\n\n"
            "TASK: Create a high-quality, engaging web lesson in Markdown based on the notes.\n\n"
            "CRITICAL RULES:\n"
            "1. LANGUAGE: All explanations MUST be in ENGLISH. Only the examples are in Spanish.\n"
            "2. TRANSLATIONS: For every Spanish vocabulary word or phrase, provide the ENGLISH and CHINESE (Simplified) translations.\n"
            "3. TONE: Be fun and motivating! Use emojis (👋 🇪🇸 🌮).\n"
            "4. NO EXERCISES: Do NOT include quizzes or practice sections in the text.\n"
            "5. STRUCTURE: Use short paragraphs and H2 subtitles.\n"
            "6. NO METADATA."
        )

        completion = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        )
        return completion.choices[0].message.content.strip()
