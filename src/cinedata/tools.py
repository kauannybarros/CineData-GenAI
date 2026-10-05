"""Ferramenta LangChain de consultas SQL sobre a camada Gold."""

from pathlib import Path

from langchain_core.tools import BaseTool, tool

from cinedata.database import QueryLimits, execute_query


def create_sql_tool(db_path: Path, *, limits: QueryLimits | None = None) -> BaseTool:
    """Cria uma ferramenta com banco e limites fixados pelo aplicativo."""

    @tool
    def query_database(sql: str) -> dict:
        """Consulta a camada Gold SQLite usando uma única instrução SELECT ou WITH ... SELECT.

        Use apenas as dez tabelas analíticas do esquema fornecido. Escrita, comandos
        administrativos e leitura de tabelas técnicas são proibidos. O retorno contém
        colunas e linhas posicionais; truncated indica corte de linhas e shortened_cells
        indica textos abreviados. row_count é a quantidade devolvida, não o total de
        correspondências. Erros vêm em error com code e message. Nunca invente resultados
        quando ok for falso. Use agregações SQL para totais e médias sobre toda a base.
        """
        return execute_query(db_path, sql, limits=limits)

    return query_database
