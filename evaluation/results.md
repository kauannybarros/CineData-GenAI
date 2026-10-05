# Resultados da avaliação

Banco da atividade, com data de referência de 04/10/2026. O SHA-256 da base está
registrado nos relatórios; todas as consultas usam acesso somente leitura.

## Referências e testes locais

As 14 consultas de referência executam sobre a base completa com os limites do
executor. Os testes com dados pequenos e respostas conhecidas verificam empates,
ausências financeiras, orçamento zero, notas sem votos, datas de lançamento,
gêneros sem filmes e associações a várias produtoras.

- [references.json](references.json): resultados esperados das 14 perguntas.
- `python -m unittest discover -s tests -v`: testes sem consumo da API.

Em 04/10/2026, a instalação foi reproduzida em uma cópia isolada do projeto,
com ambiente virtual novo em Python 3.12.3, dependências de `requirements.lock`
e `.env.example` sem chave. Os 29 testes passaram, assim como análise e formatação
do Ruff e `pip check`. A CLI confirmou as dez tabelas analíticas em modo somente
leitura e contou 95.645 filmes na base fornecida. Essa validação local não consumiu
chamadas ao modelo. O workflow do GitHub executa as verificações de código e testes;
a validação com a base fornecida foi feita localmente.

## Comparações com o OpenRouter

| Relatório | Casos | Dados aprovados | Divergências | Erros do agente | Chamadas |
| --- | ---: | ---: | ---: | ---: | ---: |
| [live.json](live.json) | 14 | 8 | 4 | 2 | 29 |
| [recheck.json](recheck.json) | 6 | 3 | 0 | 3 | 13 |
| [final-check.json](final-check.json) | 3 | 1 | 0 | 2 | 5 |
| [delivery-check.json](delivery-check.json) | 2 | 1 | 0 | 1 | 4 |

Total registrado nesses relatórios: 51 chamadas ao modelo. As primeiras 47 foram
feitas com a conta anterior; as quatro de `delivery-check.json`, com a nova conta.
Esses totais não são um contador diário da conta nem incluem uso fora dos relatórios.
O router `openrouter/free` selecionou
modelos diferentes entre chamadas. Os relatórios preservam SQL, resultados,
respostas textuais, modelos reportados e erros; não contêm a chave da API.

As execuções têm configurações distintas: `live.json` usou 4.096 tokens e escolha
automática de ferramenta; `recheck.json` usou 4.096 tokens, ferramenta específica
obrigatória e esforço de raciocínio baixo; `final-check.json` usou 8.192 tokens,
escolha `required` e orçamento de duas chamadas por pergunta. A configuração atual
usa 8.192 tokens, ferramenta obrigatória inicialmente e três chamadas por pergunta.
`delivery-check.json` usou essa configuração, com orçamento global de seis chamadas.
Os resultados não representam uma execução integral dessa configuração atual.

Em conjunto, 13 das 14 perguntas tiveram uma resposta concluída com pelo menos uma
consulta coincidente com a referência. Isso é um resultado acumulado de execuções
diferentes, não uma taxa de acerto de uma única execução.

| Pergunta | Evidência aprovada |
| --- | --- |
| Top receitas | `live.json` |
| Margem por filme | `live.json` |
| Popularidade | `live.json` |
| Divergência TMDB/IMDb | `final-check.json` |
| Média IMDb por ano | `live.json` |
| Ator com mais filmes recentes | `live.json` |
| Diretores com mínimo de cinco filmes | `live.json` |
| Dupla ator–diretor | `recheck.json` |
| Quantidade por gênero | `live.json` |
| Produtora com maior lucro | `live.json` |
| Gênero com maior margem média | `recheck.json` |
| Lucro médio por gênero | `delivery-check.json` |
| Divergência usuários/IMDb | `recheck.json` |

**Filmes mais avaliados** permanece sem resposta concluída e validada. Em execuções
anteriores, o modelo inventou uma coluna `titulo` em `dim_reviews`, corrigiu o join,
mas atingiu o orçamento, e também deixou de aplicar desempates determinísticos.
Na verificação mais recente, `nvidia/nemotron-3-ultra-550b-a55b:free` encerrou sem
chamar a ferramenta, apesar de `tool_choice=required`. O retorno foi rejeitado com
`no_query_result`. Essa chamada reportou 2.933 tokens de entrada e 273 de saída,
totalizando 3.206; esse valor não representa os tokens de toda a verificação.

Lucro médio por gênero, que anteriormente também falhava sem consulta, foi aprovado
na verificação mais recente. Não foram feitas novas tentativas para o caso restante.

## Correções e cuidados

O prompt reforça filtros de votos, divisão em ponto flutuante, uma linha por filme
antes de agregar margem por gênero, desempates por nome/título e chave, localização
correta do título e materialização das CTEs de atores/diretores. A exigência inicial
de ferramenta é aplicada pelo código, mas um provedor ainda pode devolver texto
sem respeitá-la; nesse caso a resposta é rejeitada.

O limite de trabalho do SQLite passou de 20 para 50 milhões de instruções, mantendo
o limite de 10 segundos. A referência de duplas executou em aproximadamente seis
segundos; a referência de atores recentes, em aproximadamente cinco segundos.
Consultas com planos menos eficientes ainda podem ser interrompidas.

A comparação aceita qualquer consulta bem-sucedida que coincida integralmente com
a referência e registra seu identificador em `matched_query_id`. Isso permite
consultas auxiliares posteriores, sem confundi-las com o resultado principal.
A quantidade e a ordem das linhas são verificadas, inclusive os empates.

`passed` certifica coincidência dos dados consultados com esta referência. Não
certifica todas as afirmações da resposta textual nem consultas livres fora do
conjunto avaliado. A diferença entre as execuções evidencia a variabilidade do
router gratuito. Confira os relatórios ao escolher um modelo específico para uso
consistente e controle o consumo no painel do OpenRouter.
