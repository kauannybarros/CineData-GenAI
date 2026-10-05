# CineData Analytics

Projeto da atividade GenAI do Rocket Lab 2026: agente em Python para consultar o
catálogo de filmes em linguagem natural sobre a camada Gold SQLite.

## Funcionalidades

Agente Text-to-SQL integrado ao OpenRouter e ferramenta SQLite restrita. É possível
verificar o ambiente, executar SQL localmente e fazer perguntas em linguagem natural
pelo terminal. As análises têm critérios documentados e consultas de referência.

Consulte o [modelo de dados](docs/data-model.md) e as
[regras de negócio](docs/business-rules.md). Os metadados e achados são reproduzíveis:

```bash
python scripts/profile_database.py --reference-date 2026-10-04
```

## Stack

- Python 3.12 ou superior e SQLite da biblioteca padrão.
- LangChain como framework de agentes, com integração `langchain-openrouter`.
- Modelo padrão `openrouter/free`, seguindo o tutorial da atividade.
- `python-dotenv` para configuração e Ruff para análise e formatação.

A integração oferece suporte a ferramentas conforme a
[documentação do LangChain](https://docs.langchain.com/oss/python/integrations/chat/openrouter).
O suporte e a disponibilidade dependem do modelo selecionado. O router pode escolher
modelos diferentes entre chamadas.

## Preparação e execução

Execute os comandos na raiz do repositório, em Linux/macOS:

```bash
git clone https://github.com/kauannybarros/CineData-GenAI.git
cd CineData-GenAI
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -c requirements.lock -e '.[dev]'
cp .env.example .env
```

Se o `.env` já existir, mantenha suas configurações em vez de copiá-lo novamente.
No Windows, ative o ambiente com `.venv\Scripts\Activate.ps1`.
O repositório é privado: a clonagem exige uma conta com acesso. Use Python 3.12
para reproduzir o ambiente validado.

1. Obtenha `cinerocket.db` na pasta compartilhada da atividade. Nesta máquina ele já
   está em `cinerocket-db/cinerocket (1).db`. Em outra máquina, coloque-o nesse caminho
   ou ajuste `CINEDATA_DB_PATH` no `.env`.
2. Crie sua chave em [OpenRouter Keys](https://openrouter.ai/keys) e preencha
   `OPENROUTER_API_KEY` no `.env`. A chave nunca deve ser colocada no código ou no Git.
3. Mantenha `OPENROUTER_MODEL=openrouter/free` inicialmente ou configure outro
   identificador compatível com ferramentas.
4. Verifique o ambiente:

```bash
cinedata check
# Depois de preencher a chave:
cinedata check --require-key
```

A verificação abre o banco somente para leitura e confirma a presença das 10 tabelas
da atividade. O arquivo fornecido também contém `alembic_version`, uma tabela de
controle de migrações, totalizando 11 tabelas.
Ela não envia requisições à API, não imprime a chave e não valida a autenticação.
Também funciona com `python -m cinedata.cli check`.

O banco e o tutorial original são arquivos locais fornecidos pela atividade e não
são versionados. O banco precisa ser obtido separadamente por quem clonar o projeto.

## Qualidade e dependências

```bash
ruff check src scripts tests
ruff format --check src scripts tests
python -m unittest discover -s tests -v
python -m pip check
```

Os testes usam banco temporário e modelo simulado: cobrem consultas, joins, CTEs,
funções de janela, bloqueios de escrita, truncamento, interrupção, o ciclo completo
do agente, correção de SQL e limites de chamadas. Não dependem de chave OpenRouter,
não enviam requisições e não alteram o banco da atividade.

O workflow [quality.yml](.github/workflows/quality.yml) executa essas verificações
em Python 3.12 a cada push e pull request, sem banco da atividade ou chave de API.

`pyproject.toml` declara as dependências; `requirements.lock` registra as versões
instaladas e verificadas em Python 3.12.3. Para atualizar o conjunto, use um ambiente
virtual novo, instale `python -m pip install -e '.[dev]'`, valide o ambiente e gere:

```bash
python -m pip list --format=freeze --exclude cinedata-analytics > requirements.lock
```

Planeje os testes antes de chamar o modelo. O tutorial da atividade informa uma cota
de 50 requisições diárias em contas sem créditos; confira seu uso no
[painel do OpenRouter](https://openrouter.ai/activity). Perguntas do agente podem
exigir mais de uma chamada.

## Estrutura

```text
src/cinedata/          Configuração, CLI, SQLite, ferramenta, prompts e agente
tests/                Testes do executor e do agente sem chamadas à API
evaluation/           Relatórios com referências e resultados comparados
docs/data-model.md     Dicionário, relacionamentos e qualidade dos dados
docs/business-rules.md Critérios das análises e mapeamento das perguntas
docs/schema.sql        Esquema extraído do banco
docs/database-profile.json  Metadados e resultados de verificações
scripts/profile_database.py  Reprodução da inspeção em modo somente leitura
.env.example          Configuração de exemplo, sem segredos
pyproject.toml        Metadados, dependências e configuração do Ruff
requirements.lock     Versões instaladas
.github/workflows/quality.yml  Verificações automáticas de qualidade
cinerocket-db/         Banco local, ignorado pelo Git
```

## Consultas locais e ferramenta SQL

Exemplo sem consumo da API:

```bash
cinedata query 'SELECT COUNT(*) AS filmes FROM dim_movies'
cinedata query 'SELECT titulo FROM dim_movies ORDER BY titulo, sk_movie_id' --max-rows 5
```

O retorno JSON contém `ok`, `columns`, `rows`, `row_count`, `max_rows`, `truncated`
e `shortened_cells`. As linhas são listas alinhadas com as colunas, preservando
inclusive aliases duplicados. `row_count` conta somente as linhas devolvidas;
`truncated=true` indica que existem mais resultados. Totais e médias devem ser
calculados no SQL, sobre a amostra completa. Textos acima do limite são abreviados
e essa ocorrência é indicada em `shortened_cells`.

Em falhas, `ok=false` e `error` traz `code` e `message`, sem resultados parciais.
O comando encerra com código 1 quando a consulta falha. Principais códigos:
`invalid_sql`, `forbidden_sql`, `database_unavailable`, `query_limit`, `sqlite_error`
e `unsupported_result`.

O executor aceita uma única instrução `SELECT` ou `WITH ... SELECT`. Há três
camadas de restrição: conexão `mode=ro`, `query_only` e autorizador do SQLite.
O autorizador libera apenas as dez tabelas analíticas e funções internas listadas
em `database.py`. Bloqueia escrita, comandos administrativos, anexação de bancos,
extensões e acesso a tabelas técnicas, inclusive através de CTEs. A execução usa
`execute`, que rejeita múltiplas instruções.

Limites padrão: 100 linhas devolvidas, 10 segundos, 50 milhões de instruções da máquina
virtual SQLite, SQL com até 20.000 caracteres, 32 colunas e 2.000 caracteres por célula.
O mecanismo também limita valores/linhas a 100.000 bytes, profundidade de expressões
a 100 e consultas compostas a 20 termos. Resultados binários e números não finitos
são rejeitados.

O limite de tempo é verificado periodicamente pelo SQLite e ao final da leitura;
não é um isolamento de processo nem uma garantia de interrupção em exatamente
10 segundos. O número de instruções também é verificado por intervalos. Consultas
complexas podem precisar ser simplificadas ou ter seus limites ajustados pelo
aplicativo. O modelo não recebe argumentos para ampliar os limites.

Para usar a ferramenta diretamente em Python:

```python
from cinedata.config import load_settings
from cinedata.tools import create_sql_tool

sql_tool = create_sql_tool(load_settings().db_path)
result = sql_tool.invoke({"sql": "SELECT COUNT(*) AS filmes FROM dim_movies"})
```

`create_sql_tool` aceita `limits=QueryLimits(...)` para configuração pelo aplicativo.
A CLI permite ajustar somente a quantidade devolvida, entre 1 e 1.000 linhas.
Os limites restringem execução e acesso; a correção da interpretação financeira
e dos joins é orientada pelos prompts e verificada com consultas de referência.

## Perguntas em linguagem natural

Preencha sua chave no `.env` antes de usar estes comandos, que consomem chamadas ao
OpenRouter. O esquema é inspecionado localmente e as regras essenciais estão em
`src/cinedata/prompts.py`; o agente não precisa carregar os arquivos em `docs/`.

```bash
cinedata ask 'Quantos filmes há no catálogo?'
cinedata ask 'Quais são os 10 filmes com maior bilheteria em reais?' --show-sql
cinedata ask 'Qual a nota média IMDb por ano de lançamento?' --json
cinedata ask 'Qual ator participou de mais filmes lançados nos últimos cinco anos?' --reference-date 2026-10-04
```

O agente exige a ferramenta na primeira chamada, recebe o resultado e explica a análise em
português. `--show-sql` apresenta as consultas propostas; `--json` inclui resposta,
consultas, resultados, data de referência e número de chamadas ao modelo. Uma consulta
proposta pode falhar; confira `result.ok` no JSON para saber se foi executada com sucesso.

Cada pergunta é independente, sem memória de conversa. Por padrão a data de referência
é a data atual em São Paulo; `--reference-date` torna os períodos reproduzíveis.
O orçamento é de até três chamadas ao modelo e três à ferramenta por pergunta.
Normalmente uma chamada ao modelo gera SQL e outra explica os dados; a terceira permite
uma correção. Ajuste `CINEDATA_MAX_MODEL_CALLS` no `.env` entre 2 e 5 se necessário.
Esse controle usa o
[middleware de limites do LangChain](https://docs.langchain.com/oss/python/langchain/middleware/built-in#model-call-limit).

Retentativas automáticas do SDK estão explicitamente desativadas. O timeout de cada
requisição é de 45 segundos; a geração é limitada a 8.192 tokens. O limite de chamadas
é por pergunta, não um contador diário persistente. O router pode usar modelos diferentes
nas chamadas; consulte o painel para controlar o consumo real da conta.

Falhas de chave, cota/capacidade, rede e execução do agente são apresentadas sem imprimir
credenciais ou detalhes privados de exceções. Não há resposta analítica aceita sem ao
menos uma consulta bem-sucedida. Se o modelo encerrar sem consultar o banco, a aplicação
retorna `no_query_result`; reformule a pergunta. Perguntas fora do catálogo e pedidos de
esclarecimento também podem receber esse retorno. Isso verifica a presença de evidência,
mas não garante que toda interpretação do modelo esteja correta.

Erros encerram a CLI com código 1. O modo JSON preserva consultas já concluídas mesmo
quando uma chamada posterior falha. Exemplos de códigos: `missing_key`,
`authentication_error`, `rate_limit`, `connection_error`, `model_timeout`,
`agent_limit` e `no_query_result`. Em 429, confira capacidade/cota no painel antes de
tentar novamente; não há fallback automático que consuma chamadas adicionais.

Validação inicial: em 04/10/2026, uma pergunta real de contagem gerou SQL, executou
a ferramenta e respondeu 95.645 filmes, usando duas chamadas ao modelo gratuito.
Esse teste confirma autenticação e tool calling nessa execução, sem substituir a
avaliação das cinco categorias de perguntas.

## Avaliação das análises

Consulte [os resultados e limitações da avaliação](evaluation/results.md).

Há 14 perguntas de referência nas cinco categorias do enunciado, definidas em
`src/cinedata/evaluation_cases.py`. Cada uma contém pergunta e SQL independente do
modelo. A data padrão da avaliação é 04/10/2026 para manter os períodos reproduzíveis.

Para executar as referências sobre o banco local, sem consumir a API:

```bash
cinedata evaluate
```

O relatório é salvo em `evaluation/references.json`, com SQL, valores esperados,
tempos e SHA-256 do banco. Os testes também verificam as referências com um banco
pequeno de respostas conhecidas, cobrindo finanças ausentes, margem com orçamento
zero, notas sem votos, filmes futuros, gêneros vazios e empates.

Para comparar com o agente, consumindo chamadas ao OpenRouter:

```bash
cinedata evaluate --live --max-calls 30 --output evaluation/live.json
# Recorte menor:
cinedata evaluate --live --case receita --case imdb_ano --max-calls 6 --output evaluation/sample.json
```

A avaliação real reserva o orçamento máximo por pergunta antes de iniciá-la, não
ultrapassa o orçamento global e interrompe chamadas após erro de cota, autenticação,
saldo ou conexão. Casos não executados ficam como `skipped`. O orçamento padrão é
10 chamadas; aumente-o conforme a cota disponível na conta. Não há retentativas
automáticas.

Para tornar a comparação reproduzível, a pergunta enviada ao agente inclui os nomes
e a ordem das colunas esperadas, sem fornecer SQL ou respostas calculadas. A comparação
verifica quantidade, ordem e valores das linhas de consultas bem-sucedidas. Pelo menos
uma deve coincidir com a referência; consultas auxiliares não substituem essa evidência.
Aliases não são usados para decidir equivalência. Valores numéricos têm tolerância
absoluta de 0,011 e relativa de 1e-12 para acomodar apresentação com duas casas.
Resultados truncados ou abreviados não são aprovados.

O relatório registra a pergunta, o SQL de referência, as consultas do agente,
as respostas textuais, os modelos reportados e o consumo de chamadas. `passed`
significa que os dados coincidem com a referência; `mismatch` indica divergência;
`agent_error` ou `reference_error` indicam falha de execução. A comparação de dados
não certifica todas as afirmações do texto gerado nem todas as perguntas possíveis.
O comando retorna código 1 se houver divergências, erros ou casos não executados.

Não substitua o banco por outro arquivo e reutilize resultados antigos como se fossem
da mesma base: confira o SHA-256 e a data do relatório. Consultas livres não recebem
o contrato de colunas usado na avaliação.

Use `--calls-per-question 2` para reduzir o orçamento por pergunta, sabendo que uma
correção de SQL pode exigir uma terceira chamada para a resposta final. Para comparar
novamente um relatório já salvo, sem novas chamadas:

```bash
cinedata evaluate --rescore evaluation/live.json
```

O limite de tokens também abrange raciocínio em muitos provedores; respostas podem
ser cortadas antes de produzir SQL ou texto. Consulte `diagnostics` em falhas sem
consulta e a [documentação de tokens de raciocínio do OpenRouter](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens).
