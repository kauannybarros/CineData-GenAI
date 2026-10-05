"""Perguntas e SQL de referência independentes das respostas do modelo."""

from dataclasses import dataclass


@dataclass(frozen=True)
class EvaluationCase:
    id: str
    category: str
    question: str
    sql: str


CASES = (
    EvaluationCase(
        "receita",
        "financas",
        "Quais são os 10 filmes com maior receita em reais?",
        """SELECT m.titulo, f.receita_brl FROM dim_movies m
        JOIN fact_movies_performance f USING(sk_movie_id) WHERE f.receita_brl IS NOT NULL
        ORDER BY f.receita_brl DESC, m.titulo, m.sk_movie_id LIMIT 10""",
    ),
    EvaluationCase(
        "lucro_genero",
        "financas",
        "Qual o lucro médio em reais por gênero, considerando apenas receita informada? "
        "Mostre a quantidade de filmes e quantos não têm orçamento. Ordene pelo gênero.",
        """SELECT g.nome_genero, AVG(f.lucro_brl) AS lucro_medio_brl,
        COUNT(*) AS filmes, SUM(f.orcamento_brl IS NULL) AS sem_orcamento
        FROM dim_genres g JOIN bridge_movie_genre b USING(sk_genre_id)
        JOIN fact_movies_performance f USING(sk_movie_id) WHERE f.receita_brl IS NOT NULL
        GROUP BY g.sk_genre_id ORDER BY g.nome_genero, g.sk_genre_id""",
    ),
    EvaluationCase(
        "margem",
        "financas",
        "Quais os 10 filmes com maior margem de lucro percentual, com finanças informadas?",
        """SELECT m.titulo, 100.0*(f.receita_brl-f.orcamento_brl)/f.receita_brl AS margem_percentual
        FROM dim_movies m JOIN fact_movies_performance f USING(sk_movie_id)
        WHERE f.receita_brl>0 AND f.orcamento_brl IS NOT NULL
        ORDER BY margem_percentual DESC, m.titulo, m.sk_movie_id LIMIT 10""",
    ),
    EvaluationCase(
        "popularidade",
        "popularidade",
        "Quais são os cinco filmes mais populares?",
        """SELECT m.titulo, f.popularidade FROM dim_movies m
        JOIN fact_movies_performance f USING(sk_movie_id) WHERE f.popularidade IS NOT NULL
        ORDER BY f.popularidade DESC, m.titulo, m.sk_movie_id LIMIT 5""",
    ),
    EvaluationCase(
        "divergencia_notas",
        "popularidade",
        "Quais os 10 filmes com maior divergência entre TMDB e IMDb? "
        "Mostre as notas e a diferença.",
        """SELECT m.titulo, f.nota_tmdb, f.nota_imdb,
        ABS(f.nota_tmdb-f.nota_imdb) AS divergencia FROM dim_movies m
        JOIN fact_movies_performance f USING(sk_movie_id)
        WHERE f.nota_tmdb BETWEEN 0 AND 10 AND f.qtd_tmdb>0
        AND f.nota_imdb BETWEEN 0 AND 10 AND f.qtd_imdb>0
        ORDER BY divergencia DESC, m.titulo, m.sk_movie_id LIMIT 10""",
    ),
    EvaluationCase(
        "imdb_ano",
        "popularidade",
        "Qual a nota média IMDb por ano? "
        "Mostre a quantidade de filmes avaliados e ordene pelo ano.",
        """SELECT m.ano_lancamento, AVG(f.nota_imdb) AS nota_media, COUNT(*) AS filmes
        FROM dim_movies m JOIN fact_movies_performance f USING(sk_movie_id)
        WHERE f.nota_imdb BETWEEN 0 AND 10 AND f.qtd_imdb>0
        GROUP BY m.ano_lancamento ORDER BY m.ano_lancamento""",
    ),
    EvaluationCase(
        "ator",
        "elenco",
        "Qual ator tem mais participações em filmes lançados nos últimos cinco anos? "
        "Mostre a quantidade e todos os empatados, ordenando pelo nome.",
        """WITH counts AS (SELECT p.sk_person_id, p.nome_pessoa,
        COUNT(DISTINCT b.sk_movie_id) AS filmes FROM dim_people p
        JOIN bridge_movie_person b USING(sk_person_id) JOIN dim_movies m USING(sk_movie_id)
        WHERE p.tipo_pessoa='Ator' AND m.status_filme='Lançado'
        AND m.data_lancamento BETWEEN '{five_years_ago}' AND '{reference_date}'
        GROUP BY p.sk_person_id)
        SELECT nome_pessoa, filmes FROM counts WHERE filmes=(SELECT MAX(filmes) FROM counts)
        ORDER BY nome_pessoa, sk_person_id""",
    ),
    EvaluationCase(
        "diretores",
        "elenco",
        "Quais os 10 diretores com maior nota média IMDb, com mínimo de cinco filmes avaliados? "
        "Mostre média e quantidade de filmes.",
        """SELECT p.nome_pessoa, AVG(f.nota_imdb) AS nota_media,
        COUNT(DISTINCT b.sk_movie_id) AS filmes FROM dim_people p
        JOIN bridge_movie_person b USING(sk_person_id)
        JOIN fact_movies_performance f USING(sk_movie_id)
        WHERE p.tipo_pessoa='Diretor' AND f.nota_imdb BETWEEN 0 AND 10 AND f.qtd_imdb>0
        GROUP BY p.sk_person_id HAVING COUNT(DISTINCT b.sk_movie_id)>=5
        ORDER BY nota_media DESC, p.nome_pessoa, p.sk_person_id LIMIT 10""",
    ),
    EvaluationCase(
        "dupla",
        "elenco",
        "Qual dupla ator–diretor mais trabalhou junta? "
        "Mostre ator, diretor e quantidade de filmes, "
        "com todos os empatados, ordenando pelo nome do ator e diretor.",
        """WITH actors AS MATERIALIZED (
        SELECT b.sk_movie_id, p.sk_person_id, p.nome_pessoa FROM bridge_movie_person b
        JOIN dim_people p USING(sk_person_id) WHERE p.tipo_pessoa='Ator'),
        directors AS MATERIALIZED (
        SELECT b.sk_movie_id, p.sk_person_id, p.nome_pessoa FROM bridge_movie_person b
        JOIN dim_people p USING(sk_person_id) WHERE p.tipo_pessoa='Diretor'),
        counts AS (SELECT a.sk_person_id AS ator_id, d.sk_person_id AS diretor_id,
        a.nome_pessoa AS ator, d.nome_pessoa AS diretor, COUNT(DISTINCT a.sk_movie_id) AS filmes
        FROM actors a JOIN directors d USING(sk_movie_id)
        GROUP BY a.sk_person_id, d.sk_person_id)
        SELECT ator, diretor, filmes FROM counts WHERE filmes=(SELECT MAX(filmes) FROM counts)
        ORDER BY ator, diretor, ator_id, diretor_id""",
    ),
    EvaluationCase(
        "generos",
        "generos_produtoras",
        "Qual a quantidade de filmes por gênero, incluindo gêneros sem filmes? Ordene pelo gênero.",
        """SELECT g.nome_genero, COUNT(DISTINCT b.sk_movie_id) AS filmes FROM dim_genres g
        LEFT JOIN bridge_movie_genre b USING(sk_genre_id) GROUP BY g.sk_genre_id
        ORDER BY g.nome_genero, g.sk_genre_id""",
    ),
    EvaluationCase(
        "produtora",
        "generos_produtoras",
        "Qual produtora tem maior lucro total em reais dos filmes associados, com receita e "
        "orçamento informados? Mostre o lucro e todos os empatados, ordenando pelo nome.",
        """WITH profits AS (SELECT c.sk_company_id, c.nome_produtora,
        SUM(f.receita_brl-f.orcamento_brl) AS lucro_total_brl FROM dim_companies c
        JOIN bridge_movie_company b USING(sk_company_id)
        JOIN fact_movies_performance f USING(sk_movie_id)
        WHERE f.receita_brl IS NOT NULL AND f.orcamento_brl IS NOT NULL GROUP BY c.sk_company_id)
        SELECT nome_produtora, lucro_total_brl FROM profits
        WHERE lucro_total_brl=(SELECT MAX(lucro_total_brl) FROM profits)
        ORDER BY nome_produtora, sk_company_id""",
    ),
    EvaluationCase(
        "margem_genero",
        "generos_produtoras",
        "Qual gênero tem maior margem de lucro percentual média, com dados completos? "
        "Mostre margem média, quantidade de filmes e todos os empatados, ordenando pelo gênero.",
        """WITH margins AS (SELECT g.sk_genre_id, g.nome_genero,
        AVG(100.0*(f.receita_brl-f.orcamento_brl)/f.receita_brl) AS margem_media,
        COUNT(*) AS filmes FROM dim_genres g JOIN bridge_movie_genre b USING(sk_genre_id)
        JOIN fact_movies_performance f USING(sk_movie_id)
        WHERE f.receita_brl>0 AND f.orcamento_brl IS NOT NULL GROUP BY g.sk_genre_id)
        SELECT nome_genero, margem_media, filmes FROM margins
        WHERE margem_media=(SELECT MAX(margem_media) FROM margins)
        ORDER BY nome_genero, sk_genre_id""",
    ),
    EvaluationCase(
        "avaliacoes",
        "usuarios",
        "Quais os 10 filmes mais avaliados pelos usuários locais? "
        "Mostre a quantidade de avaliações.",
        """SELECT m.titulo, r.qtd_avaliacoes_usuarios FROM dim_movies m
        JOIN dim_reviews r USING(sk_movie_id) WHERE r.qtd_avaliacoes_usuarios>0
        ORDER BY r.qtd_avaliacoes_usuarios DESC, m.titulo, m.sk_movie_id LIMIT 10""",
    ),
    EvaluationCase(
        "divergencia_usuarios",
        "usuarios",
        "Quais os 10 filmes em que a nota média dos usuários locais mais diverge da IMDb? "
        "Mostre as duas notas e a diferença.",
        """SELECT m.titulo, r.nota_media_usuarios, f.nota_imdb,
        ABS(r.nota_media_usuarios-f.nota_imdb) AS divergencia FROM dim_movies m
        JOIN dim_reviews r USING(sk_movie_id) JOIN fact_movies_performance f USING(sk_movie_id)
        WHERE r.qtd_avaliacoes_usuarios>0 AND r.nota_media_usuarios BETWEEN 0 AND 10
        AND f.nota_imdb BETWEEN 0 AND 10 AND f.qtd_imdb>0
        ORDER BY divergencia DESC, m.titulo, m.sk_movie_id LIMIT 10""",
    ),
)
