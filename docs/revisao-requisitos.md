# Revisão do enunciado — Smart Charge

Revisão preparada em 22/11/2026 para entrega pelo link do repositório, conforme orientação recebida pelo responsável pelo projeto. O roteiro do README substitui a necessidade de explicação presencial: o professor executa os fluxos na própria instalação.

Esta matriz aponta implementações verificáveis, sem equivaler a uma atribuição de nota. A existência do arquivo não prova, por si só, funcionamento: consulte os testes e os passos de validação. Não há certificação para uso em carregadores físicos.

## Aplicação e integração

| Exigência | Implementação e evidência | Como conferir |
| --- | --- | --- |
| Evolução do mesmo problema | Três pontos de recarga; sessões, energia/bateria e manutenção dos módulos de potência. Protótipo preservado em `backend/legacy/` e `iot/wokwi/`. | Dashboard e histórico Git. |
| Vue/React + TypeScript + Vite | Vue 3 em `frontend/src/`, build em `infra/frontend.Dockerfile`. | `npm run build` ou Compose. |
| Chart.js/ECharts | Chart.js para ocupação, histórico dos sensores e previsto × real. | Dashboard, histórico e Laboratório. |
| FastAPI e API REST, sem Node como backend | `backend/api/main.py` e módulos de rotas. Node compila o frontend; Nginx o serve. | `/docs` e `compose.yaml`. |
| WebSocket ao vivo | Snapshot autenticado; eventos recebidos do RabbitMQ, sem conexão direta simulador–navegador. | `backend/api/realtime.py`, `/api/ws`; testes de segurança. |
| Dispositivo Python em lugar de ESP32 | `services/simulator.py` e `simulation.py`. | Telemetria dos três pontos. |
| ≥3 sensores, ≥2 atuadores | Temperatura, corrente e tensão em cada ponto; limitador e contator. Nove canais de sensores e seis atuadores no total. | Dashboard/3D/cadastro de 18 componentes. |
| Equipamento com três variáveis e degradação | Três módulos de potência; falha eleva temperatura/corrente e reduz tensão/eficiência sob carga. | Injeção de falha; testes de simulação/IA. |
| Regra automática e controle Web | Proteção térmica local com histerese; contator/limite comandados pela Web. | `services/rules.py`, `simulation.py`, `tests/integration.py`. |
| MQTT bidirecional, ACLs e autenticação | Mosquitto com conta por estação; gateway confirma publicações e repassa comandos. | `gateway.py`, `bootstrap.py`; comando confirmado pela telemetria. |
| PostgreSQL com usuários/dispositivos/configurações/regras/alertas/auditoria | Esquema em `api/schema.sql`; `automation_rules` registra a política fixa compartilhada com o simulador. Faixas/configuração por componente. | `/api/rules`, `/api/catalog`, auditoria; `review_integration.py`. |
| InfluxDB com leituras e telemetria | Gravador consome RabbitMQ e escreve em `charging_telemetry`; histórico de sensores consultado na API. | `writer.py`, `/api/telemetry/history`, gráfico histórico. |
| Cadastro/gerenciamento IoT | Inicialização dos três pontos e 18 componentes; edição de nome/localização/faixas/permissões, com revisão concorrente e auditoria. | Dispositivos; `management_integration.py`. |

## RabbitMQ

| Exigência | Evidência |
| --- | --- |
| Exchange topic e routing keys de tipo/dispositivo | Exchange `events`, contratos e publicação em `services/common.py`; definições em `infra/bootstrap.py`. |
| Quatro consumidores distintos no fluxo ao vivo | `writer.telemetry`, `inference.telemetry`, `api.events`, `gateway.commands`. |
| Filas de geração/treinamento | `generator.jobs` e `trainer.jobs`; API apenas dispara tarefas, workers executam. |
| DLQ preservada e JSON único | `deadletters`; envelope `id`, `timestamp`, `type`, `device_id`, `payload`. Prévia faz requeue. |
| Usuário por serviço, permissões mínimas, sem guest | Credenciais/bootstrap e permissões de recurso/tópico; monitor sem escrita/configuração. |
| Tela ao vivo via API de gerenciamento no backend | Mensageria: quantidades, taxas, consumidores, eventos recentes e DLQ. Navegador não conhece a senha do broker. |
| Consumidor parado acumula e depois drena fila | Roteiro do README; teste de navegador `infra/management-browser-test.mjs`. |

“Todo dado passa pelo RabbitMQ” se aplica aos fluxos internos de telemetria, comandos, previsões, alertas e jobs. Login, cadastro e consultas históricas são operações REST/SQL/InfluxDB: não são artificialmente convertidos em eventos IoT. O writer persiste telemetria em paralelo à entrega WebSocket/inferência; leituras históricas são recuperadas do InfluxDB.

## Dados sintéticos e regressão

| Exigência | Evidência |
| --- | --- |
| Gerador configurável pela interface | Quantidade de equipamentos/sensores, dias, falhas/modos, ruído, faltantes, outliers e semente no Laboratório. Configurações avançadas ficam em seção expansível. |
| ≥1 milhão, NumPy em blocos e teto | De 1 a 3 milhões de leituras completas; geração em blocos de 5.000; Parquet por equipamento. `services/ml/generation.py`. |
| Degradação progressiva, sobreposição/ruído e ciclo diário | Falhas graduais e variações periódicas na geração; `test_ml.py` valida reprodutibilidade e qualidade. |
| Rótulos verdadeiros fora da telemetria | Arquivos de treino incluem saúde, degradação e tempo até a falha; simulador publica apenas sinais e estado da recarga. |
| Jobs em segundo plano com progresso | RabbitMQ, `lab_worker.py`, tabelas `jobs`/`job_outbox` e atualizações WebSocket. |
| Dois modelos de regressão | `HistGradientBoostingRegressor` para saúde e RUL, não classificação substituindo regressão. |
| Mesmo código de features e janelas causais | `ml/features.py` compartilhado por treino e inferência; janela de até 16 leituras; teste impede consulta a leituras futuras. |
| Divisão por equipamento | Grupos treino/validação/teste distintos; testes verificam ausência de interseção. |
| MAE, RMSE, R², gráfico e importância | Laboratório apresenta tabela, comparação previsto × real e importância por permutação. |
| Baseline e aprovação real | Comparação com média; ambos os alvos precisam vencer MAE e RMSE. Versão reprovada não substitui a vigente. |
| Atualização sem reiniciar e versão visível | Worker recarrega versão aprovada; Insights mostra versão efetivamente carregada e avisos. |
| Inferência RabbitMQ e alertas com histerese | Worker publica previsão/alerta no barramento; três previsões ruins e dez boas sob carga. `test_inference.py` e `inference_integration.py`. |
| Insights de saúde/RUL/tendência/alertas | Tela Insights e mesmos valores enviados ao 3D. Sem modelo/carga/dados, mostra a limitação correspondente. |

## Three.js e assistente

| Exigência | Evidência |
| --- | --- |
| Cena viva, só WebSocket, congelada sem dados | `DigitalTwin.vue`, `twin-scene.ts`, `twin.ts`; freshness e congelamento testados. Câmera pode ser manipulada manualmente mesmo sem telemetria. |
| Todos os itens, IDs comuns e posições somente no frontend | Três estações × seis componentes; cadastro no PostgreSQL, offsets no frontend. |
| Cores normal/atenção/crítico/sem dados | Faixas do cadastro e níveis preditivos; ausência de dados prevalece. |
| Atuadores e ambiente reativos | Contator/limitador, partículas nos cabos, baterias/carros, calor e movimento do módulo dependem dos sinais recebidos. Não há sensor de vibração: o movimento usa degradação/saúde, não uma leitura inexistente. |
| Clique, leitura, minigráfico, saúde e comandos | Raycast e botões acessíveis equivalentes; RBAC para comandos. |
| Cabos com extremidades corretas; desempenho | Coordenadas testadas, variantes conectado/estacionado; `InstancedMesh`, estado reaproveitado e descarte dos recursos. |
| LLM local, pequeno, CPU, no Compose | Ollama `qwen2.5:1.5b`, sem API de nuvem nem chave externa, pré-carregamento pelo `ollama-init`. |
| Resumo preparado no backend, só leitura | `api/assistant.py`; contexto de leituras, previsões, alertas, métricas e arquitetura. Sem ferramentas SQL/execução/atuação. |
| Streaming, carregando modelo e cancelamento | Eventos NDJSON, buffering desligado no Nginx, interface e botão de interrupção. |
| Saída não confiável, limite e auditoria | Markdown sem HTML/imagens/links navegáveis; cinco consultas aceitas por minuto/usuário; cada pergunta auditada. Testes de unidade, integração real e Chrome. |

## Segurança, execução e entrega

- JWT com três papéis, bcrypt, limite de tentativas, revogação e ticket WebSocket sem JWT na URL: `api/security.py` e `tests/security_integration.py`.
- Segredos aleatórios em volumes, exportação local ignorada, permissões MQTT/AMQP e contas por serviço: `infra/bootstrap.py` e scripts de credenciais. Não enviar `secrets/` ao GitHub.
- Python 3.12 e frontend sem root; somente frontend publicado. Serviços com healthcheck e dependências; tarefas de inicialização são oneshot e terminam com zero.
- Um comando constrói/sobe a stack. GitHub Actions verifica build e unidades; não substitui os testes completos com brokers e LLM. A execução remota do workflow só pode ser confirmada depois do push.
- README contém proposta, arquitetura, contas sem senhas, instalação Windows/Linux/macOS, primeira geração/treino e roteiro de avaliação independente.

## Limites explicitados ao avaliador

1. Cadastro gerencia os três pontos existentes; adicionar/remover estações/IDs exigiria expandir simulador, ACLs e layout. Não há promessa de provisionamento arbitrário de hardware.
2. Política térmica registrada no PostgreSQL é fixa e versionada em código, não um editor remoto de regras. Faixas editáveis do cadastro mudam cores; não mudam automaticamente a política térmica nem a histerese da IA.
3. Instalação nova não traz regressões treinadas. É preciso gerar dados e treinar; os artefatos da máquina do autor não fazem parte do Git.
4. RUL é limitada a 168 h; regressão sintética e LLM pequeno têm erro. O assistente pode explicar fatos incorretamente; os painéis e a arquitetura documentada são as referências verificáveis.
5. Interfaces administrativas de InfluxDB/RabbitMQ/pgAdmin são opcionais no enunciado e permanecem fechadas. Por isso não se oferecem links para serviços inexistentes. A aplicação inclui monitoramento próprio e API autenticada.
6. O histórico Git real é preservado; não se fabrica contribuição de integrantes. Para a entrega, utilize o link da branch `desenvolvimento-bimestre2`, que contém a versão revisada.

## Evidências da execução desta revisão

### Atualização visual a partir da referência enviada

A identidade visual foi adaptada para preto/grafite e verde-lima, com tipografia maior nos títulos, navegação em cápsulas, cards compactos e novo login. O carregador ilustrado em SVG foi criado para o projeto, sem copiar imagens do portfólio de referência nem depender de fontes/imagens remotas. O dashboard mantém o acesso aos sensores e controles avançados e ganhou um resumo com dados do WebSocket (conexão, vagas, potência recebida e alertas). A paleta também foi aplicada a gráficos, assistente e cena 3D. A build, os sete testes TypeScript e a verificação no Chrome em desktop/celular passaram; o diagnóstico 3D confirmou animação, modo compatível, reinicialização, raycast e ausência de avisos/exceções gráficas.

Verificações realizadas em 22/11/2026 no Docker Desktop/WSL2, com Python 3.12 nos containers:

- Build de produção do frontend e da imagem Python; 23 testes unitários Python e sete testes TypeScript aprovados. As unidades Python também executaram em container sem bancos, brokers ou volumes de segredos, validando o comando do CI.
- Segurança: JWT obrigatório e assinatura, três papéis, revogação no logout, ticket WebSocket de uso único/expirado, limite de tentativas, auditoria e aplicação PostgreSQL sem superusuário.
- Fluxo de comandos: contator aberto zera potência/corrente; limite altera a recarga; entrada/saída cria/encerra sessão. Os estados originais foram restaurados.
- Cadastro e mensageria: atualização por WebSocket, revisão concorrente, bloqueio de comandos, faixas inválidas rejeitadas e DLQ inspecionada sem remoção. Cadastros restaurados.
- Histórico novo e regra persistida: leitura autenticada nos três papéis, temperatura/corrente/tensão em ordem, limite de tamanho e parâmetros inválidos rejeitados.
- Chrome: controles expansíveis preservados, gráfico histórico Chart.js desenhado, parâmetros avançados disponíveis, navegação coerente e Dashboard sem overflow em 390 px.
- Revisão visual detectou erro no primeiro frame do 3D: o timestamp de `requestAnimationFrame` podia preceder o `performance.now()` da inicialização, gerando deslocamento negativo das partículas fora da curva do cabo. O intervalo agora é limitado a zero–50 ms. O novo teste cobre esse caso; o teste Chrome passou a verificar animação real e ausência de erro tratado, além de pixels não vazios, modo compatível, reinicialização, raycast, congelamento sem simulador e comando do contator com restauração.
- **Instalação com volumes novos:** projeto temporário `smart-charge-verificacao`, porta 8081, sem reutilizar banco, credenciais, conjuntos, regressões ou volume do Ollama originais. A stack subiu com `docker compose up -d --build`; o modelo de linguagem foi baixado nesse volume novo. Ao final, o ambiente temporário foi removido e a stack original restaurada.
- Nessa instalação nova, a integração gerou **1.000.000 de leituras / 3.000.000 de medições**, treinou os dois modelos e aprovou ambos contra baseline. Métricas observadas: saúde MAE **2,432**, RMSE **7,277**, R² **0,765**, baseline MAE **8,229**; RUL MAE **5,692 h**, RMSE **15,556 h**, R² **0,708**, baseline MAE **16,767 h**. São resultados dessa configuração/semente; não substituem as métricas calculadas na instalação do avaliador.
- Inferência no ambiente novo: falha reduziu saúde de aproximadamente 97,75 para 56,34, gerou alerta persistido e entregou previsão/alerta por WebSocket. Recuperação encerrou o alerta com histerese; versão e estados foram restaurados pelo teste.
- Ollama real no ambiente novo: resposta em fluxo concluída em cerca de **77 segundos**, consultas auditadas, três papéis, limite de frequência, concorrência e cancelamento verificados; nenhuma linha adicionada à caixa de comandos de atuação. Esse é um teste funcional de integração, não uma certificação de exatidão factual do texto gerado.
- `npm audit` após atualização das dependências: **zero vulnerabilidades reportadas**. Resultado pontual do catálogo consultado; não representa garantia permanente de ausência de falhas.

As validações descritas acima foram executadas localmente. O workflow remoto é disparado pelo push; seu resultado atualizado pode ser consultado na aba Actions do GitHub. Para avaliação, utilize a branch `desenvolvimento-bimestre2`.
