# Regras de interpretação das análises

Estas são decisões de projeto para a futura implementação do agente, baseadas no
[modelo inspecionado](data-model.md) e no enunciado. Não são funcionalidades já
implementadas nem regras descobertas no DDL. O usuário pode pedir outros critérios;
a resposta deve explicitar os filtros e fórmulas realmente usados.

## Convenções gerais

- A unidade de contagem é o filme identificado por `sk_movie_id`, nunca o título.
- O universo padrão é o catálogo disponível. Não aplicar filtros de status,
  quantidade mínima de votos ou período que não tenham sido pedidos ou explicados.
- Quando a pergunta disser “lançados”, usar `status_filme = 'Lançado'` e
  `data_lancamento <= :reference_date`. Existem filmes futuros no catálogo.
- “Receita”, “faturamento” e “bilheteria” referem-se a `receita_*`.
- Valores monetários usam BRL por padrão; pedidos em dólares usam as colunas USD.
  Não misturar moedas nem converter com uma taxa externa.
- Ausência (`NULL`) é dado desconhecido, não zero. Informar quando filtros por
  disponibilidade reduzem a amostra. Resultados vazios não provam ausência no mundo real.
- Rankings usam o limite solicitado, sem máximo arbitrário de 10. Na ausência de
  limite, usar 10 e informar. Desempatar por título/nome e, por último, pela chave.
- “Quem mais” retorna todos os empatados na primeira posição; “top N” retorna N
  linhas com desempate determinístico e informa que há empates se relevante.
- Arredondar apenas a apresentação: dinheiro e médias com duas casas decimais,
  margens em porcentagem. Ordenar e calcular com os valores não arredondados.
- As métricas são do snapshot local; “tempo real” significa consultar o arquivo na
  execução, sem afirmar atualização ao vivo das fontes externas.

## Finanças

Receita informada significa `receita_brl IS NOT NULL`; orçamento informado significa
`orcamento_brl IS NOT NULL`. Se forem necessários divisores, eles também devem ser
positivos. As mesmas regras valem para USD. Não usar `COALESCE` para criar uma receita
ou orçamento ausente.

O banco contém `lucro_brl` e `lucro_usd`, mas seus valores seguem uma lógica que
substitui receita/orçamento ausentes por zero. Para lucro com finanças completas,
calcular `receita_brl - orcamento_brl`, exigindo os dois campos informados. Usar esse
valor consistentemente nas margens e na comparação de produtoras. A diferença para
o lucro BRL armazenado pode chegar a um centavo por arredondamento.

A pergunta do enunciado “lucro médio por gênero, considerando apenas filmes com
receita informada” é uma exceção explícita: usar `AVG(lucro_brl)` com receita
informada e explicar que o orçamento pode faltar. Apresentar o tamanho da amostra
e quantos filmes não têm orçamento. Se o usuário exigir custo conhecido, exigir
também orçamento e usar a diferença recalculada. Não restringir a amostra
silenciosamente nem chamar o lucro com custo ausente de rentabilidade comprovada.

**Margem de lucro** é `100.0 * (receita_brl - orcamento_brl) / receita_brl`, com ambos
informados e receita positiva. Prejuízos são válidos e geram margens negativas.
Orçamento zero, se existir numa futura base, não impede margem sobre receita.

**ROI**, quando solicitado, é `100.0 * (receita_brl - orcamento_brl) / orcamento_brl`,
com receita informada e orçamento positivo. ROI e margem têm denominadores distintos.
Usar `100.0` ou `1.0` nas divisões, pois SQLite pode realizar divisão inteira para
valores armazenados como inteiros, apesar do tipo declarado `NUMERIC`.

“Margem média” significa média aritmética das margens individuais, não a divisão
entre lucros e receitas totais. Uma margem agregada/ponderada deve ser identificada
explicitamente e calculada somente se solicitada.

## Notas, popularidade e avaliações

Notas IMDb/TMDB observadas e notas locais estão na escala 0–10. Para análises de
notas externas, exigir nota não nula, na faixa 0–10, e quantidade de votos positiva
na respectiva plataforma. Zero com votos é uma nota válida; zero sem votos não é
uma observação avaliada. Essa é uma política de qualidade, a ser explicada na resposta.

- Divergência entre notas: diferença absoluta (`ABS(nota_a - nota_b)`). Mostrar as
  duas notas e a diferença; não usar a diferença assinada para ordenar divergência.
- Média por ano/diretor: média aritmética por filme. Só ponderar por votos quando
  solicitado. Por padrão, “nota média” sem plataforma usa IMDb e informa essa escolha;
  se a pergunta exigir comparação entre plataformas, manter cada origem separada.
- Popularidade: usar `popularidade`, excluindo nulos. Ela não é nota, quantidade de
  votos, receita ou número de avaliações locais.
- “Usuários”/“avaliações dos usuários”: usar `dim_reviews`, com quantidade positiva
  e média não nula. “Mais avaliados” usa quantidade, não maior nota.
- Para médias de avaliações individuais, filtrar/agregar `movie_reviews` antes de
  juntar outras dimensões. `AVG(nota_media_usuarios)` é média por filme;
  `SUM(nota_media_usuarios * qtd_avaliacoes_usuarios) / SUM(qtd_avaliacoes_usuarios)`
  é média ponderada pelas avaliações, com divisão em ponto flutuante.

## Pessoas, gêneros e produtoras

Filtrar papéis por `dim_people.tipo_pessoa`: `Ator`, `Diretor` ou `Roteirista`.
Contar filmes distintos por chave da pessoa/papel. Não fundir chaves por nome.
Não há personagens, ordem de créditos ou duração de participação neste modelo.

Para diretores com mínimo de cinco filmes, aplicar `HAVING COUNT(DISTINCT
sk_movie_id) >= 5` sobre filmes com nota válida para a média, e mostrar a contagem.
Assim, cinco filmes no catálogo com somente uma nota não bastam para o ranking.

Para dupla ator–diretor, juntar a ponte duas vezes pelo mesmo filme, filtrando os
papéis nas respectivas dimensões e agrupando pelo par de chaves. Contar filmes
distintos. Um nome igual nos dois papéis não garante que se trate da mesma pessoa;
sem identidade externa, não eliminar ou fundir esse par silenciosamente.

O gênero e a produtora recebem o valor integral dos filmes associados, sem rateio
entre grupos. “Produtora com maior lucro total” deve ser descrita como lucro dos
filmes associados à produtora, não lucro contábil da empresa. Não há participação
financeira de cada produtora na base.

Gêneros são armazenados em inglês. Usar o mapa abaixo para perguntas em português;
validar nomes com `dim_genres`, sem presumir categorias fora do catálogo.

| Português | Valor no banco | Português | Valor no banco |
| --- | --- | --- | --- |
| Ação | Action | Aventura | Adventure |
| Animação | Animation | Comédia | Comedy |
| Crime | Crime | Documentário | Documentary |
| Drama | Drama | Família | Family |
| Fantasia | Fantasy | História / Histórico | History |
| Terror | Horror | Música | Music |
| Mistério | Mystery | Romance | Romance |
| Ficção científica | Science Fiction | Suspense / Thriller | Thriller |
| Filme para TV | Tv Movie | Guerra | War |
| Faroeste | Western | | |

## Períodos

“Últimos cinco anos” usa uma janela móvel de cinco anos civis, inclusiva, encerrada
em `:reference_date`, informada na resposta. Na referência de 04/10/2026, o intervalo
é 04/10/2021–04/10/2026. Para 29/02 sem equivalente no ano inicial, usar 28/02.
Calcular a janela móvel no aplicativo e fornecer as datas ISO no contexto do agente,
sem depender do relógio do SQLite. Se o usuário pedir cinco anos completos, excluir o ano corrente
e usar os cinco anos anteriores. Não confundir cinco anos com 1.825 dias.

Agrupamentos por ano usam `ano_lancamento`. Perguntas sobre filmes lançados precisam
também respeitar status e limite da data. Informar o intervalo de cobertura do banco
quando a pergunta ultrapassar 2016–2029 ou pressupuser um catálogo histórico completo.

## Mapeamento dos exemplos do enunciado

| Pergunta | Caminho e métrica | Filtros/cuidados |
| --- | --- | --- |
| Top 10 receitas em R$ | Filme → desempenho; ordenar `receita_brl` | Receita informada; 10 filmes |
| Lucro médio por gênero com receita | Gênero → ponte → desempenho; `AVG(lucro_brl)` | Receita informada; informar falta de orçamento |
| Filmes com maior margem | Filme → desempenho; lucro recalculado / receita | Ambos informados; receita positiva |
| Cinco filmes mais populares | Filme → desempenho; `popularidade` | Indicador não nulo; cinco filmes |
| Divergência TMDB/IMDb | Filme → desempenho; `ABS(nota_tmdb - nota_imdb)` | Notas e votos válidos nas duas fontes |
| Nota IMDb média por ano | Filme → desempenho; `AVG(nota_imdb)` por ano | IMDb válida; informar quantidade por ano |
| Ator com mais filmes nos últimos cinco anos | Pessoa → ponte → filme; filmes distintos | Papel `Ator`, lançados, janela móvel; preservar empates |
| Diretores com melhor média, mínimo cinco filmes | Pessoa → ponte → filme → desempenho | Papel `Diretor`, IMDb válida, cinco filmes avaliados |
| Dupla ator–diretor mais frequente | Duas pontes e duas dimensões de pessoas | Papéis separados; par de chaves; filmes distintos; empates |
| Quantidade por gênero | Gênero → ponte; filmes distintos | Incluir gênero sem filmes com LEFT JOIN e contagem da chave do filme |
| Produtora com maior lucro total | Produtora → ponte → desempenho; soma do lucro recalculado | Receita e orçamento informados; atribuição integral; preservar empates |
| Gênero com maior margem média | Gênero → ponte → desempenho; média das margens | Receita positiva e orçamento informado; média não ponderada; empates |
| Filmes mais avaliados por usuários | Filme → `dim_reviews`; quantidade local | Avaliações positivas; não usar contagem IMDb/TMDB |
| Divergência usuários/IMDb | Filme → desempenho e `dim_reviews`; diferença absoluta | IMDb válida e avaliação local válida |

## Aplicação no agente

Os critérios essenciais orientam o agente por meio de `src/cinedata/prompts.py`,
junto com o esquema real inspecionado localmente. Este documento explica os critérios
para desenvolvedores e não é carregado durante a execução. Mudanças de critérios
devem atualizar tanto este documento quanto o prompt. 
