"""Tabelas Markdown geradas dos resultados SQL, sem interpretação pelo modelo."""

from typing import Any


def _cell(value: Any) -> str:
    if value is None:
        return "Não informado"
    text = str(value)
    # Mantém células em uma linha e impede que dados criem estrutura Markdown.
    for character in "\\|`*_[]<>":
        text = text.replace(character, "\\" + character)
    return "".join(
        {"\n": r"\n", "\r": r"\r", "\t": r"\t"}.get(character, f"\\x{ord(character):02x}")
        if ord(character) < 32 or ord(character) == 127
        else character
        for character in text
    )


def render_query_tables(queries: list[dict[str, Any]]) -> str:
    """Exibe cada consulta bem-sucedida, preservando ordem, colunas e valores.

    Não escolhe a consulta principal nem certifica a interpretação do SQL.
    Números usam a representação do Python, sem arredondamento adicional.
    """
    tables = []
    for number, query in enumerate(queries, start=1):
        result = query.get("result", {})
        if not result.get("ok"):
            continue
        columns = result["columns"]
        rows = result["rows"]
        lines = [
            f"Consulta {number} — dados retornados pelo banco",
            "",
            "| " + " | ".join(_cell(column) for column in columns) + " |",
            "| " + " | ".join("---" for _ in columns) + " |",
        ]
        for row in rows:
            lines.append("| " + " | ".join(_cell(value) for value in row) + " |")
        lines.extend(["", f"Linhas exibidas: {len(rows)}."])
        if not rows:
            lines.append("A consulta não retornou linhas.")
        if result.get("truncated"):
            lines.append("Resultado parcial: existem mais linhas além das exibidas.")
        if shortened := result.get("shortened_cells"):
            lines.append(f"Textos abreviados pelo executor em {shortened} célula(s).")
        tables.append("\n".join(lines))
    return "\n\n".join(tables)
