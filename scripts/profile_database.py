"""Documenta o banco local com metadados e agregados, sem modificar seus dados."""

import argparse
import json
import sqlite3
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from cinedata.config import PROJECT_ROOT, load_settings

QUERIES = {
    "financas": """
        SELECT COUNT(*) AS filmes,
               SUM(receita_brl IS NULL) AS receita_nula,
               SUM(orcamento_brl IS NULL) AS orcamento_nulo,
               SUM(receita_brl = 0) AS receita_zero,
               SUM(orcamento_brl = 0) AS orcamento_zero,
               SUM(receita_brl < 0 OR orcamento_brl < 0) AS valores_negativos,
               SUM(receita_brl > 0 AND orcamento_brl > 0) AS ambos_positivos,
               SUM(receita_brl IS NOT NULL AND orcamento_brl IS NULL)
                   AS receita_sem_orcamento,
               SUM(receita_brl IS NULL AND orcamento_brl IS NULL) AS ambos_nulos,
               SUM(ABS(lucro_usd - (COALESCE(receita_usd, 0)
                   - COALESCE(orcamento_usd, 0))) > 0.015) AS lucro_usd_divergente,
               MAX(ABS(lucro_brl - (COALESCE(receita_brl, 0)
                   - COALESCE(orcamento_brl, 0)))) AS maior_diferenca_lucro_brl,
               MIN(1.0 * receita_brl / NULLIF(receita_usd, 0)) AS cambio_receita_min,
               MAX(1.0 * receita_brl / NULLIF(receita_usd, 0)) AS cambio_receita_max
        FROM fact_movies_performance
    """,
    "notas": """
        SELECT MIN(nota_tmdb) AS tmdb_min, MAX(nota_tmdb) AS tmdb_max,
               SUM(nota_tmdb IS NULL) AS tmdb_nula,
               SUM(nota_tmdb = 0) AS tmdb_zero,
               SUM(nota_tmdb IS NOT NULL AND qtd_tmdb > 0) AS tmdb_com_votos,
               SUM(nota_tmdb = 0 AND qtd_tmdb > 0) AS tmdb_zero_com_votos,
               MIN(nota_imdb) AS imdb_min, MAX(nota_imdb) AS imdb_max,
               SUM(nota_imdb IS NULL) AS imdb_nula,
               SUM(nota_imdb = 0) AS imdb_zero,
               SUM(nota_imdb IS NOT NULL AND qtd_imdb > 0) AS imdb_com_votos,
               SUM(nota_imdb IS NULL AND qtd_imdb > 0) AS imdb_nula_com_votos,
               MIN(popularidade) AS popularidade_min,
               MAX(popularidade) AS popularidade_max,
               SUM(popularidade IS NULL) AS popularidade_nula
        FROM fact_movies_performance
    """,
    "datas": """
        SELECT MIN(data_lancamento) AS data_min, MAX(data_lancamento) AS data_max,
               SUM(data_lancamento IS NULL) AS data_nula,
               SUM(ano_lancamento IS NULL) AS ano_nulo,
               SUM(CAST(strftime('%Y', data_lancamento) AS INTEGER)
                   != ano_lancamento) AS ano_divergente,
               SUM(strftime('%Y', data_lancamento) IS NULL) AS data_invalida
        FROM dim_movies
    """,
    "status": """
        SELECT status_filme, COUNT(*) AS quantidade
        FROM dim_movies GROUP BY status_filme ORDER BY status_filme
    """,
    "pessoas": """
        SELECT tipo_pessoa, COUNT(*) AS quantidade
        FROM dim_people GROUP BY tipo_pessoa ORDER BY tipo_pessoa
    """,
    "generos": "SELECT nome_genero FROM dim_genres ORDER BY nome_genero",
    "cobertura": """
        SELECT COUNT(*) AS filmes,
               SUM(NOT EXISTS(SELECT 1 FROM bridge_movie_genre b
                   WHERE b.sk_movie_id = m.sk_movie_id)) AS sem_genero,
               SUM(NOT EXISTS(SELECT 1 FROM bridge_movie_company b
                   WHERE b.sk_movie_id = m.sk_movie_id)) AS sem_produtora,
               SUM(NOT EXISTS(SELECT 1 FROM bridge_movie_person b
                   WHERE b.sk_movie_id = m.sk_movie_id)) AS sem_pessoas
        FROM dim_movies m
    """,
    "avaliacoes": """
        SELECT COUNT(*) AS filmes, MIN(nota_media_usuarios) AS nota_min,
               MAX(nota_media_usuarios) AS nota_max,
               SUM(nota_media_usuarios IS NULL) AS nota_nula,
               MIN(qtd_avaliacoes_usuarios) AS qtd_min,
               MAX(qtd_avaliacoes_usuarios) AS qtd_max
        FROM dim_reviews
    """,
    "consistencia_avaliacoes": """
        WITH r AS (
            SELECT sk_movie_id, COUNT(*) AS qtd, AVG(rating) AS nota
            FROM movie_reviews GROUP BY sk_movie_id
        )
        SELECT COUNT(*) AS filmes_em_ambas,
               SUM(d.qtd_avaliacoes_usuarios != r.qtd) AS contagem_divergente,
               SUM(ABS(d.nota_media_usuarios - r.nota) > 0.01) AS media_divergente,
               (SELECT COUNT(*) FROM dim_reviews d2 WHERE NOT EXISTS(
                   SELECT 1 FROM r WHERE r.sk_movie_id = d2.sk_movie_id))
                   AS agregados_sem_reviews,
               (SELECT COUNT(*) FROM r WHERE NOT EXISTS(
                   SELECT 1 FROM dim_reviews d2 WHERE d2.sk_movie_id = r.sk_movie_id))
                   AS reviews_sem_agregado
        FROM dim_reviews d JOIN r ON r.sk_movie_id = d.sk_movie_id
    """,
    "multiplos_papeis": """
        SELECT COUNT(*) AS nomes_com_multiplos_papeis FROM (
            SELECT nome_pessoa FROM dim_people GROUP BY nome_pessoa
            HAVING COUNT(DISTINCT tipo_pessoa) > 1
        )
    """,
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "docs")
    parser.add_argument(
        "--reference-date",
        type=date.fromisoformat,
        default=datetime.now(ZoneInfo("America/Sao_Paulo")).date(),
    )
    args = parser.parse_args()
    settings = load_settings()
    schema = []
    report = {"reference_date": args.reference_date.isoformat(), "tables": {}, "checks": {}}
    with closing(sqlite3.connect(f"{settings.db_path.as_uri()}?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        for row in conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ):
            name = row["name"]
            quoted_name = '"' + name.replace('"', '""') + '"'
            schema.append(row["sql"] + ";")
            report["tables"][name] = {
                "row_count": conn.execute(f"SELECT COUNT(*) FROM {quoted_name}").fetchone()[0],
                "columns": [dict(r) for r in conn.execute(f"PRAGMA table_info({quoted_name})")],
                "foreign_keys": [
                    dict(r) for r in conn.execute(f"PRAGMA foreign_key_list({quoted_name})")
                ],
                "indexes": [dict(r) for r in conn.execute(f"PRAGMA index_list({quoted_name})")],
            }
        for row in conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND sql IS NOT NULL ORDER BY name"
        ):
            schema.append(row["sql"] + ";")
        for label, sql in QUERIES.items():
            report["checks"][label] = [dict(r) for r in conn.execute(sql)]
        report["checks"]["lancados_futuros"] = [
            dict(r)
            for r in conn.execute(
                "SELECT COUNT(*) AS quantidade FROM dim_movies "
                "WHERE status_filme = 'Lançado' AND data_lancamento > ?",
                (args.reference_date.isoformat(),),
            )
        ]
        report["checks"]["foreign_key_violations"] = [
            dict(r) for r in conn.execute("PRAGMA foreign_key_check")
        ]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "database-profile.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output_dir / "schema.sql").write_text(
        "-- Esquema extraído do banco da atividade. Apenas documentação.\n\n"
        + "\n\n".join(schema)
        + "\n",
        encoding="utf-8",
    )
    print(
        f"Metadados e agregados exportados para {args.output_dir}; "
        "banco aberto somente para leitura."
    )


if __name__ == "__main__":
    main()
