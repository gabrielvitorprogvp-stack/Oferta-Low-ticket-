# 📡 RADAR LOW TICKET — ESCALA EMERGENTE

Sistema de inteligência de mercado que garimpa **produtos digitais low ticket no Brasil** na
Meta Ads Library e em sinais públicos, guarda **memória histórica por anunciante** e detecta
**quem está acelerando agora**.

> Métrica principal: **aceleração de criativos ao longo do tempo** (snapshots), não volume absoluto.

---

## 1. Como funciona (uma rodada)

```
 SEMENTES ──► A. Descoberta (≥30 consultas na Meta Ads Library)
 (+ palavras        │   anúncios → agrupados por anunciante (page_id)
  expandidas)       ▼
              B. Triagem  ── produto real? low ticket? oferta direta? funil? resposta direta?
                    │       (descartados ficam registrados com o motivo)
                    ▼
              C. Análise Meta do anunciante (view_all_page_id)
                    │   todos os anúncios ativos → ofertas (por URL de destino)
                    │   → SNAPSHOT (criativos, novos 7/14/30/40d, antigos ativos, hooks, formatos)
                    ▼
              D. Landing page  ── headline, promessa, mecanismo, preço, bônus, garantia,
                    │              urgência, checkout, order bump, VSL/quiz, screenshot
                    ▼
              E. Expansão  ── novas palavras-chave extraídas das ofertas → próximas rodadas
                    │          (SEMENTE → OFERTA → NOVAS PALAVRAS → NOVOS ANUNCIANTES)
                    ▼
              F. Demanda  ── Brave/Bing/DDG/Google, Reddit, fóruns (fontes salvas)
                    ▼
              G. Scoring  ── Velocity + confiança · Mar Azul + confiança · detector de
                             aceleração · estágio · status (watchlist) · alertas → Telegram
```

Cada etapa é isolada: se uma fonte falha, a rodada continua e registra o que ficou
`PARTIAL` / `NOT_VERIFIED`. Nada é inventado: o que não foi observado não pontua e derruba a
confiança.

---

## 2. Análise técnica da Meta Ads Library (testada na prática)

Tudo abaixo foi verificado durante o desenvolvimento, não suposto.

| Comportamento | O que o Radar faz |
|---|---|
| A 1ª página de resultados (~30 anúncios) vem **embutida no HTML** como JSON estruturado (`search_results_connection`): id, `start_date`, `collation_count`/`collation_id`, formato, copy, CTA, link, página, categorias. | Lê esse JSON (mais estável que o DOM). Há fallback por texto do DOM (rótulos pt-BR), marcado como `PARTIAL`. |
| A busca por anunciante (`view_all_page_id`) informa o **total de anúncios ativos**. Para anunciantes pequenos (<30 anúncios, justamente a faixa da escala emergente) a 1ª página cobre **100%** → `VERIFIED`. | Esse total alimenta os snapshots. Cobertura <100% fica `PARTIAL` e reduz a confiança. |
| A paginação (rolar a página) chama GraphQL `AdLibrarySearchPaginationQuery`; **sem login a Meta responde "Rate limit exceeded" (code 1675004)** rapidamente. | Tenta devagar; ao primeiro rate limit para e marca `PARTIAL`. Nunca extrapola. |
| Com muitas requisições, a Meta passa a servir uma **página de desafio JS (`__rd_verify`) em loop** e depois `ERR_TOO_MANY_RETRIES` — limite de taxa por IP. Em IP de datacenter isso persistiu por >10 min. | `ThrottledError` → cooldown progressivo (60s, 120s, 240s). Se persistir, **pausa a Meta na rodada**, mantém candidatos `pending_meta` e tenta na próxima rodada. Não contorna a proteção. |
| `xfb_ad_library_is_captcha_required`, login wall, checkpoint. | `BlockedError` → pausa + alerta **"Intervenção necessária"** + `python -m radar login`. **Nunca tenta resolver CAPTCHA.** |
| Só aparecem anúncios **ativos**; anúncios pausados somem. Não há gasto/alcance para anúncios comerciais no BR. | A "curva retroativa" por datas de início tem **viés de sobrevivência** — por isso o sinal sem histórico é rotulado *estimado* e limitado a `FORTE`. A aceleração real vem dos snapshots. |
| "Esse anúncio tem várias versões" / mesmo criativo em vários conjuntos. | **Fingerprint de criativo** (texto + título + formato + id da mídia): duplicações técnicas contam 1 vez. |
| Checkouts (ex.: Kiwify) **convertem o preço pela localização do IP** (vimos US$ fora do Brasil). | Só registra preços em **R$**; moeda estrangeira vira nota "conversão por IP — ignorado". Parcelas (`12x de R$ 6,93`) e mensalidades são ignoradas. |
| A API oficial (`ads_archive`) só cobre anúncios políticos/temas sociais fora da UE. | Não serve para ofertas comerciais no BR; por isso browser automation. |

### O que é automatizado com segurança
- Busca por palavra-chave e por anunciante, 1ª página completa, total de anúncios ativos.
- Snapshots históricos, métricas de criativos, aceleração, scores, watchlist, alertas.
- Landing pages, screenshots, checkout (1 salto), extração de estrutura do funil.
- Expansão de palavras-chave e clusters de nicho emergentes.

### O que pode exigir sessão/login/intervenção
- **Paginação além de ~30 anúncios** por anunciante grande (rate limit sem login) — com sessão
  logada no perfil persistente (`python -m radar login`) o limite costuma ser bem maior.
- **Volume alto de consultas a partir de IP de datacenter/VPS** — rode de IP residencial ou
  reduza `DISCOVERY_MIN_QUERIES` / aumente `META_MIN_DELAY_S`.
- **Google** (CAPTCHA em IP de datacenter) e **Reddit** (bloqueio de rede) — o Radar marca
  `BLOCKED`/`NOT_VERIFIED`. Para validação de demanda estável use `BRAVE_API_KEY`.
- Qualquer CAPTCHA/checkpoint: o Radar pausa e pede intervenção; você resolve no navegador.

---

## 3. Classificação, scores e detector de aceleração

**Estágios**: `TESTE` (≤3 criativos, sem sinal) · `ESCALA_EMERGENTE` (≥10 criativos com
maioria dos últimos 40d e novos em 14d, ou ≥6 com aceleração forte medida) · `ESCALA_MADURA`
(≥60 anúncios/≥45 criativos sem aceleração, ou maioria antiga sem crescimento).

**Detector de aceleração** (sobre a série de snapshots; pontos <10h são agregados):

| Série | Sinal |
|---|---|
| 12 → 18 em 3 dias | `FORTE` |
| 18 → 19 em 7 dias | `FRACA` |
| 80 → 80 | `ESTAVEL` (madura/parada) |
| 8 → 17 → 28 | `FORTISSIMA` |
| queda ≥20% | `QUEDA` → status `DECLINING` |

Também calcula `delta_3d`, `delta_7d`, `delta_14d` e `creative_growth_rate` (relativo/dia).
Esses exemplos são testes automatizados (`backend/tests/test_acceleration.py`).

**Velocity Score (0–100)** — 25% crescimento recente · 20% frequência de uploads (dias distintos
com criativo novo) · 20% sobrevivência de antigos (30d+) · 15% hooks · 10% formatos · 10%
consistência do funil. **`confidence_score` separado**: cai com cobertura parcial, poucos
snapshots, datas ausentes, fallback DOM.

**Mar Azul (0–100)** — dor, clareza, intenção de compra, concorrência no cluster, volume de
anúncios do termo na Meta, diferenciação, versão própria viável, entrega, força criativa, custo.
Heurístico e explicável (cada componente mostra a evidência). Componentes sem evidência entram
neutros e reduzem a confiança. *Atenção*: com poucos anunciantes monitorados, "concorrência
observada" tende a parecer baixa — confie mais quando a confiança passar de ~60.

**Status (watchlist)**: `NEW → TESTING/WATCHING → EMERGING → MATURE / DECLINING`, `DISCARDED`.
Revisita automática: EMERGING a cada 6h, WATCHING 20h, TESTING 3d, MATURE 7d. O status pode ser
fixado manualmente no dashboard.

**Alertas** — só com sinal relevante: `EMERGING_SCALE` (entrou em escala emergente com velocity
≥55; 1×/semana por oferta), `ACCELERATION` (aceleração `FORTE`/`FORTISSIMA` **medida** entre
snapshots; 1×/dia), `INTERVENTION_REQUIRED` (bloqueio).

**Modelagem** — extrai dor, público, mecanismo, estrutura, ângulos e modelo comercial e sugere
**diferenciação própria**. Nunca recomenda copiar marca, nome, textos, criativos, imagens, PDFs,
vídeos ou PI.

---

## 4. Arquitetura

Monolito modular (sem microserviços). Python 3.10+ · FastAPI · Playwright · SQLAlchemy 2
(SQLite; PostgreSQL via `DATABASE_URL`) · APScheduler · React + Vite.

```
backend/radar/
  crawler/      browser.py (perfil persistente, bloqueio)   meta_ads.py (meta_ads_agent)
                meta_parser.py (JSON puro, testável)         landing_page.py (landing_page_agent)
  research/     seeds.py · offer_filter.py (triagem) · niches.py · text_utils.py
                search_providers.py · demand_agent.py · modeling.py
  scoring/      metrics.py · acceleration.py · velocity.py · blue_ocean.py · classifier.py
  database/     models.py (advertisers, offers, ads, ad_snapshots, landing_pages, keywords,
                research_runs, run_logs, market_clusters, alerts, demand_evidence)
  notifications/ base.py (Notifier) · telegram.py · email.py · whatsapp.py (interface)
  scheduler/    jobs.py (cron) · lock.py (uma rodada por vez)
  api/          app.py (REST + serve o dashboard)
  pipeline.py   orquestrador (discovery → triage → monitor → landing → demand → scoring)
dashboard/      React (Radar, Watchlist, Oferta, Palavras & nichos, Rodadas & logs)
```

Agentes → módulos: `discovery_agent` = `Pipeline.discover` + `seeds`; `meta_ads_agent` =
`crawler/meta_ads.py`; `landing_page_agent` = `crawler/landing_page.py`; `demand_agent` =
`research/demand_agent.py`; `scoring_agent` = `scoring/*`; `monitor_agent` =
`Pipeline._advertiser_queue` + revisita por status.

---

## 5. Instalação e uso

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
cp ../.env.example .env        # ajuste Telegram, agendamento etc.
python -m radar init

# dashboard
cd ../dashboard && npm install && npm run build

# rodar
cd ../backend
python -m radar run                      # rodada manual completa (~15–25 min)
python -m radar run --max-queries 8 --max-advertisers 5 --skip-external   # rodada curta
python -m radar run --term "seletividade alimentar"                       # consulta específica
python -m radar serve                    # API + dashboard em http://localhost:8000
python -m radar login                    # navegador visível p/ login/verificação manual
python -m radar rescore                  # recalcula scores sem navegar
python -m radar test-telegram
```

Desenvolvimento do front com hot reload: `cd dashboard && npm run dev` (proxy para :8000).

### Usar pelo app do Claude
O radar também tem uma versão que abre dentro do claude.ai (`artifact/radar-low-ticket.html`),
publicada como artifact com banco próprio. A coleta continua rodando no computador; depois de
uma rodada, `python -m radar export-artifact` gera os JSON em `backend/data/artifact_export/`, que
o Claude envia para o banco do app ("sincronize o radar"). Mudanças de status feitas no app ficam
salvas no banco do app.

### Agendamento
- `RADAR_SCHEDULE=3x` (08h, 14h, 20h) ou `daily` (09h) ou cron (`"30 7,13,19 * * *"`), fuso
  `America/Sao_Paulo`. Roda dentro de `python -m radar serve` ou isolado com
  `python -m radar scheduler`.
- Ou cron do sistema: `0 8,14,20 * * * cd /caminho/backend && .venv/bin/python -m radar run --trigger cron`
- Cada rodada é um subprocesso; um lock de arquivo (`fcntl`) impede rodadas simultâneas e é
  liberado pelo SO se o processo morrer. Rodadas órfãs são fechadas como `failed`.

### Telegram
Crie um bot com o @BotFather, pegue o token, envie uma mensagem ao bot e obtenha o `chat_id`
(`https://api.telegram.org/bot<TOKEN>/getUpdates`). Defina `TELEGRAM_BOT_TOKEN` e
`TELEGRAM_CHAT_ID`. Email (SMTP) e WhatsApp têm a interface `Notifier` pronta.

### Testes
```bash
cd backend && python -m pytest -q
```
Inclui uma simulação de 3 rodadas (8 → 17 → 28 criativos) que verifica snapshots, sinal
`FORTISSIMA`, status `EMERGING` e geração de alertas, sem navegador.

---

## 6. Limitações conhecidas da V1 (honestas)

- A identidade da oferta é a URL de destino normalizada: o mesmo produto em URLs diferentes vira
  ofertas diferentes do mesmo anunciante.
- Triagem, nicho e Mar Azul são heurísticas em regras (auditáveis, mas imperfeitas). Um
  classificador por LLM é a evolução natural.
- Rodadas de alto volume a partir de IP de datacenter tendem a ser limitadas pela Meta (ver §2).
- Sem histórico (1º snapshot), aceleração é **estimada** pelas datas de início — confirme com as
  rodadas seguintes. O radar fica realmente útil a partir de 3+ rodadas.
