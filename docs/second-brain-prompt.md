# System Prompt: Production-Grade Engineering, Financial & Hardware Orchestrator (Evolution of LTM/STM Second Brain)

You are a Master AI Architect, Systems Engineer, and Core Database Developer. I am evolving my existing "Second Brain" project—which natively leverages Short-Term Memory (STM) and Long-Term Memory (LTM) mechanics—into an Active Hardware Orchestrator and Knowledge Graph (Agentic OS). The system is deployed inside Proxmox VE using Python 3.11+ and PostgreSQL 16 with `pgvector`.

Your objective is to design the architecture and code where the LTM/STM cognitive layer is fully augmented by a hierarchical knowledge base, financial/personal document intelligence, and real-time infrastructure controls across my local LAN (Proxmox node, Workstation with an NVIDIA RTX 5090, and MacBook Pro M1).

---

## Cognitive Layer Mapping (LTM vs STM)
1. **Short-Term Memory (STM):** Volatile session contexts, active conversational chat states, and real-time hardware telemetry (e.g., live VRAM usage on the RTX 5090 fetched on-demand via passwordless SSH).
2. **Long-Term Memory (LTM):** Persisted relational and vector knowledge. This includes the hierarchical skill tree, project artifacts, repository git log patterns, extracted structured invoice/contract properties, and historical AI research logs cached with pgvector HNSW indexing.

---

## Technical & Security Constraints
- Network: Flat Layer 2 LAN allowing direct Wake-on-LAN UDP broadcasts to offline nodes.
- Execution Protocol: Asynchronous Paramiko/AsyncSSH using pre-configured public key authentication and local host aliases.
- Privacy Isolation: A strict Dual-LLM routing paradigm. High-privacy LTM components (invoices, contracts, emails) must be processed locally inside Proxmox via an Ollama endpoint, while generic development/git workflows can utilize Cloud APIs (Claude 3.5 Sonnet).

---

## Required Deliverables

### 1. Architectural Memory Schema (PostgreSQL DDL)
Provide a complete, production-grade PostgreSQL DDL script establishing the LTM foundation:
- Tables for `skills` (hierarchical self-referencing tree), `projects` (scoped by personal/commercial), and `financial_records` (invoices and contracts parsing amount, currency, counterparty, tax IDs).
- Table for `hardware_nodes` containing structural hardware dimensions and a localized LTM state cache (`is_online`, `cached_gpu_util`, `last_seen_timestamp`) to facilitate immediate agent planning without blocking on cold hardware connections.
- Table for `unified_ltm_chunks` storing semantic vector embeddings (`vector(1536)` or local equivalents) flagged by `artifact_type` (adr, chat_transcript, email, contract, invoice, code_doc), properly mapped with relational keys and optimized HNSW indexes.

### 2. Multi-Format LTM Ingestion Pipelines (Python)
Provide robust Python classes to transition data into Long-Term Memory:
- `git_parser.py`: Analyzes commit message logs, styles, and engineering patterns linked to specific projects.
- `pdf_legal_parser.py`: Extracts layout-aware raw text from financial invoices/contracts via `pdfplumber`, mapping them to static schema entities.
- `email_archive_parser.py`: Ingests `.eml`/`.mbox` formats, discarding layout overhead while preserving headers (`From`, `To`, `Subject`) and body context.

### 3. Active STM Hardware Orchestration Modules
Provide Python components handling real-time execution and short-term state collection:
- `hardware_orchestrator.py`: Employs `wakeonlan` to send magic packets across the local subnet. It leverages `paramiko` to issue live SSH commands (`nvidia-smi` parser for the RTX 5090, system load commands for MacBook/Proxmox). It must automatically flush live results into the LTM hardware cache upon successful return.

### 4. Memory-Synthesized Omni-Search Query Engine
Write a FastAPI router (`search.py`) demonstrating a combined LTM/STM lookup. It must cleanly fulfill unified prompts like: *"Is my RTX 5090 workstation active right now? If not, wake it up. Then search my long-term memory for any private machine learning projects or contract emails associated with it."*
- Synthesizes STM parameters (real-time ping/SSH telemetry) with standard hybrid relational-vector queries across `unified_ltm_chunks` and metadata relations.

Provide fully realized, type-hinted, and modular Python/SQL implementations without any truncation or conceptual summaries.



------------
Google resonse in AI mode

1. STM (Short-Term Memory) – Pamięć Krótkotrwała
  * Live Telemetria sprzętu: Aktualny stan obciążenia RTX 5090 czy maszyn na Proxmoxie pobierany w czasie rzeczywistym przez SSH. Nie ma potrzeby trwałego składowania każdej sekundy uptime'u w LTM – to czysty kontekst operacyjny dla bieżącej sesji.
  * Kontekst konwersacji (Chat History): Ostatnie pary prompt-odpowiedź z Twojego panelu użytkownika oraz świeżo zaimportowane logi sesji (np. z Gemini).
  * Bufor Ingestii: Chwile przed tym, jak faktura w PDF czy mail zostaną w pełni przetworzone, ich surowy tekst i tymczasowe tokeny lądują w STM.
2. LTM (Long-Term Memory) – Pamięć Długotrwała (Twój nowy Knowledge Graph). To tutaj pgvector oraz struktura relacyjna PostgreSQL wykonują najważniejszą pracę:
  * Hierarchia Umiejętności i Projektów: Drzewiasta struktura Twojej kariery (parent_id), która gromadzi doświadczenie z lat ubiegłych.
  * Pamięć Finansowo-Prawna: Trwałe indeksy faktur (kwoty, NIP-y) oraz umów (daty wygaśnięcia), połączone z konkretnymi firmami z przeszłości.
  * Stylistyczna Pamięć Gita: Wzorce i konwencje Twoich commitów wyciągnięte z historii repozytoriów, które definiują Twój profil inżynierski.
  * Wektorowa baza wiedzy: Wszystkie głębokie wycinki z dokumentacji technicznej i ADR-ów zapisane jako osadzenia (embeddings) z indeksem HNSW do przeszukiwania semantycznego.

```
[ Bieżący Czat / Live Telemetria ] ──> [ STM (Short-Term Memory) ] ──> Szybki Cache / Sesja FastAPI
                                             │
                                             ▼ (Konsolidacja i wektoryzacja)
[ Projekty, Umowy, Git, Umiejętności ] ─> [ LTM (Long-Term Memory) ] ──> PostgreSQL + pgvector (HNSW)
```

Podejście hybrydowe do telemetrii — odpytywanie w czasie rzeczywistym (live) podczas interakcji z czatem, połączone z buforowaniem ostatniej znanej konfiguracji (cache) — to najlepsza praktyka inżynierska. Pozwala to na natychmiastowe planowanie zadań przez LLM bez blokowania interfejsu (unika się opóźnień sieciowych w przypadku, gdy któraś z maszyn jest uśpiona).System w tej konfiguracji idealnie mapuje się na omawiany przez Ciebie model Agentic OS oparty na frameworku ARMS:
  * Memory (Pamięć): Przechowuje stałą specyfikację (RTX 5090, M1 Pro, Proxmox) oraz "ostatni znany stan" (cached state).
  * Apps & Connectors (Aplikacje): Aktywne wtyczki SSH, klient Proxmoxa i pakiety Wake-on-LAN działające w czasie rzeczywistym

## Rozszerzenie Architektury o Warstwę Sprzętową (Orkiestracja)

```
[ Omni-Search / Chat Panel ]
                                 │
                                 ▼
                     [ FastAPI Query Engine ]
                                 │
        ┌────────────────────────┴────────────────────────┐
        ▼                                                 ▼
[ Baza pgvector / Postgres ]                      [ Hardware Tool Executor ]
├── Specyfikacja sprzętu                          ├── Wol (Wake-on-LAN)
└── Środowiska projektów                          ├── SSH (Workstation, MacBook)
                                                └── Proxmox API Client
```

1. Nowe tabele w bazie danych (Kontekst Środowiska)
   * `hardware_nodes`: Przechowuje stałe właściwości (Nazwa, MAC Adres dla WoL, IP/Host SSH, Specyfikacja: RTX 5090, M1 Pro, przydzielone klucze SSH).
   * `project_environments`: Łączy projekty z konkretnymi maszynami (np. "Projekt X: Trenowanie lokalne LLM na Workstation (RTX 5090)", "Projekt Y: Prace frontendowe na MacBook M1"). Dzięki temu agent wie, gdzie szukać kodu lub gdzie uruchomić dane zadanie.
2. Narzędzia Wykonawcze (Tools / Connectors)
   * **Moduł Budzenia (Wake-on-LAN)**: Skrypt Python używający pakietu wakeonlan do wysyłania Magic Packet na adres MAC Twojego potężnego PC, gdy agent zauważy, że maszyna jest offline, a chcesz wykonać na niej zadanie.
   * **Inspekcja Live (Paramiko / SSH)**: Ponieważ masz skonfigurowane certyfikaty i pliki hosts, Python przez bibliotekę paramiko może asynchronicznie odpalać komendy diagnostyczne (np. nvidia-smi --query-gpu=... dla RTX 5090, top lub powermetrics dla MacBooka).
   * **Integracja z Proxmoxem**: Wykorzystanie biblioteki proxmoxer do bezpośredniego odpytywania API Proxmoxa o stan klastra, uruchomione VM-ki i kontenery.

Dorzuciilbym do tego pomysły i ogólne rozmyślania z Obsidian lub Trilium. Synchronizacja na zasadzie działania engramow pamięci w mózgu - pamięć krótkotrwała, która podczas snu zapisywana jest w hipokampie (wektory w bazie). Plus licznik referencji, ktory okreslalby waznosc projektu. Jezeli nie roslby bylby wrzucany do limbo, gdzie laduja nieuzyte lub zbyt malo wazne pomysly

🧠 Neurobiologiczna Architektura Cyfrowego Mózgu (second-brain)

```
[ Obsidian / Trilium ] ──> [ STM: Bufor Engramów ] 
                                  │
                                  ▼ (Nocna konsolidacja / "Sen" systemu)
[ PostgreSQL + pgvector ] ─> [ LTM: Hipokamp (Wektory + Relacje) ]
                                  │
          ┌───────────────────────┴───────────────────────┐
          ▼ (Licznik referencji > Próg)                  ▼ (Brak aktywności / Zanikanie)
   [ Aktywna Kora ]                               [ Strefa Limbo ]
(Priorytet w kontekście LLM)                 (Archiwum / Skompresowane embeddings)
```

1. Ingestia jako Formowanie Engramów (Obsidian / Trilium)Twoje codzienne luźne myśli, pomysły na projekty i notatki z Obsidiana lub Trilium są traktowane jako surowe engramy (ślady pamięciowe).
  * STM (Pamięć Krótkotrwała): Nowe notatki i modyfikacje nie trafiają od razu do głównego indeksu długoterminowego. Lądują w szybkim, tymczasowym buforze (staging area).
  * Proces Synchroniczny: System nasłuchuje zmian w plikach markdown (Obsidian) lub przez API Trilium, natychmiast udostępniając je w STM na potrzeby bieżących rozmów z agentem.
2. Faza Snu i Konsolidacja Pamięci (Nocny Worker Celery/Cron)Wzorem ludzkiego mózgu, który podczas snu przenosi i porządkuje wspomnienia z hipokampa do kory mózgowej, Twój system uruchamia nocną rutynę konsolidacji (System Sleep Cycle):
  * Uruchamia się procesor LLM (lokalna Llama na Proxmoxie lub Claude w chmurze), który bierze surowe engramy z STM.
  * Wektoryzacja i Taksonomia: LLM generuje embeddingi, ale co ważniejsze – buduje relacje. Mapuje pomysły z Obsidiana na istniejące projekty, faktury, e-maile lub technologie.
  * Zapisuje ustrukturyzowane, powiązane dane w LTM (PostgreSQL + pgvector).
3. Licznik Referencji (Synaptic Plasticity) i Strefa Limbo (Zapominanie)W neurobiologii nieużywane połączenia synaptyczne słabną (plastyczność synaptyczna). Twój system zaimplementuje to za pomocą Licznika Referencji (Reference Counter) i flagi Limbo:
  * Każdy węzeł (projekt, pomysł, notatka) ma licznik reference_count oraz pole last_accessed_at.
  * Za każdym razem, gdy pytasz o dany temat, odwołujesz się do niego w kodzie, dostajesz powiązanego maila lub modyfikujesz notatkę – licznik rośnie, a synapsa się wzmacnia.
  * Konsolidacja do Limbo: Jeśli wskaźnik ważności projektu (wyliczany z częstotliwości referencji w czasie) spadnie poniżej określonego progu, projekt oraz jego wektory są przenoszone do Strefy Limbo (status = 'limbo').
  * Korzyść: Podczas przeszukiwania bazy (Omni-Search), dane z Limbo są domyślnie ignorowane lub mają bardzo niski priorytet (waga), co drastycznie czyści kontekst LLM z szumu i nieaktualnych pomysłów. Mogą zostać stamtąd "wybudzone", jeśli intencjonalnie o nie zapytasz.


  📝 Ostateczny Prompt dla LLM (Wersja Biomimetyczna)

  # System Prompt: Biomimetic Engineering, Financial & Hardware Orchestrator (The second-brain OS)
  
  You are a Visionary AI Architect, Neuro-inspired Systems Engineer, and Principal Database Developer. I am building a self-hosted Personal Knowledge Management System and Active Hardware Orchestrator named `second-brain`. The system simulates biological memory consolidation (STM, LTM, Sleep Cycles, Synaptic Plasticity, and Limbo/Forgetting) running inside Proxmox VE using Python 3.11+ and PostgreSQL 16 with `pgvector`.
  
  Your objective is to build a system where raw ideas and markdown thoughts (from Obsidian/Trilium) function as volatile memory engrams that undergo structured architectural consolidation into a relational-vector Long-Term Memory (LTM) graph.
  
  ---
  
  ## Biomimetic Architecture Specifications
  
  1. **Short-Term Memory (STM) & Engram Ingestion:** 
     - Volatile storage caching real-time hardware telemetry (RTX 5090 live load via SSH) and incoming markdown files from Obsidian/Trilium. 
     - New notes are stored in a raw staging layout, accessible for active chat context but not yet fully integrated into the global graph.
  
  2. **System Sleep Cycle (Memory Consolidation):**
     - An asynchronous cron/Celery worker mimicking the human brain during sleep. 
     - It processes raw STM engrams using an LLM to extract semantic links, map dependencies to physical hardware environments, career history, or financial records, generates vector embeddings, and commits them to the permanent LTM repository.
  
  3. **Synaptic Weight & Limbo (Forgetting Mechanism):**
     - Every node (project, thought, skill) features a `reference_count` and a `last_accessed_at` timestamp.
     - Every user query, code commit, or related email interaction increments this counter (Synaptic Strengthening).
     - A degradation routine evaluates decay over time. Nodes falling below a critical threshold are flagged as `status = 'limbo'`. Limbo nodes are excluded from standard RAG query semantic pools unless explicitly targeted, protecting the LLM from outdated conceptual noise.
  
  ---
  
  ## Technical Layout & Privacy
  - Subnet: Flat Layer 2 LAN for Wake-on-LAN UDP broadcasts.
  - Connectivity: Passwordless async SSH via local host configurations.
  - Isolation: Dual-LLM design. Privacy-sensitive operations (contracts, personal notes, financials) run locally on Proxmox via Ollama. General tech extraction uses Cloud APIs (Claude 3.5 Sonnet).
  
  ---
  
  ## Required Deliverables
  
  ### 1. Biomimetic Memory Schema (PostgreSQL DDL)
  Provide an un-truncated, production SQL script establishing:
  - `skills`, `projects`, `financial_records`, `emails`, and `hardware_nodes` (including LTM hardware status cache).
  - `engram_stm_buffer`: Staging table for fast insertion of active thoughts and raw content feeds.
  - `unified_ltm_chunks`: Central table containing `embedding vector(...)`, `content`, `artifact_type` (adr, code_doc, personal_note, chat, email, invoice), a `status` flag (active, limbo), and metrics fields: `reference_count` (integer) and `last_accessed_at` (timestamp).
  - Composite indexes and HNSW configurations optimized to filter out `limbo` statuses by default.
  
  ### 2. Synchronization & Sleep Consolidation Pipelines (Python)
  Provide modular Python classes for:
  - `obsidian_sync.py`: Watches or batch-reads the Obsidian directory/Trilium API, populating the `engram_stm_buffer`.
  - `sleep_cycle_worker.py`: Implements the async routine that reads the STM buffer, triggers the LLM to deduce architectural or personal taxonomy, maps nodes, pushes vectors into `unified_ltm_chunks`, and clears the STM staging buffer.
  - `synaptic_decay_agent.py`: Periodic execution module that reduces node weights based on time decay and toggles inactive contexts into `limbo`.
  
  ### 3. Active STM Hardware Orchestration Modules
  - `hardware_orchestrator.py`: Standardizes WoL execution and live Paramiko SSH scraping (GPU/VRAM telemetry for the RTX 5090), feeding fresh live snapshots back into the hardware cache.
  
  ### 4. Synapse-Weighted Omni-Search Query Engine
  Write a FastAPI router (`search.py`) handling compound prompts like: *"Is my workstation with the RTX 5090 awake? Wake it up if needed. Then query my active long-term memory for any Obsidian project ideas or notes connected to it, ignoring things that have faded into limbo."*
  - Merges real-time hardware pings with cross-relational vector operations filtered strictly to active synapse criteria (`status = 'active'`).
  
  Provide pristine, fully implemented, type-hinted Python and SQL files. No placeholders, complete logic.


  Oto charakterystyka poszczególnych warstw technologicznych:

1. Baza Danych i Pamięć Długotrwała (LTM)
   - PostgreSQL 16+: Sercem systemu jest klasyczna, relacyjna baza danych. Wybór ten jest podyktowany koniecznością utrzymania ścisłej hierarchii (drzewo umiejętności, relacje projekt-faktura-email) oraz sprawnym zarządzaniem licznikami referencji i statusami (active/limbo).
   - pgvector: Rozszerzenie do PostgreSQL, które przekształca tę relacyjną bazę w wysokowydajną bazę wektorową. Zamiast utrzymywać osobny system (jak Pinecone czy Milvus), pgvector pozwala na wykonywanie zapytań hybrydowych (np. jednoczesne filtrowanie po dacie, statusie 'active' i odległości cosinusowej wektora) w jednym zapytaniu SQL.
   - Indeksowanie HNSW (Hierarchical Navigable Small World): Wykorzystywane w pgvector do błyskawicznego przeszukiwania przestrzeni wektorowej dużej bazy wiedzy przy zachowaniu minimalnych opóźnień.
2. Backend i Orkiestracja (STM & Execution)
  - Python 3.11+: Główny język backendu, zapewniający dojrzały ekosystem do integracji z AI/LLM, bibliotekami systemowymi oraz narzędziami do parsowania danych.
  - FastAPI: Ultraszybki, asynchroniczny framework webowy służący do budowy API i obsługi zapytań z czatu/dashboardu w czasie rzeczywistym. Dzięki asyncio doskonale radzi sobie z jednoczesnym odpytywaniem maszyn przez sieć bez blokowania interfejsu.
  - SQLAlchemy 2.0 + Asyncpg: Nowoczesny system ORM do komunikacji z PostgreSQL w sposób asynchroniczny i bezpieczny (wbudowana ochrona przed SQL Injection).
3. Asynchroniczne Przetwarzanie i Faza Snu (Sleep Cycle)
  - Celery + Redis: System kolejek zadań i broker wiadomości. Celery odpowiada za uruchamianie ciężkich zadań w tle (np. cykliczny, nocny proces konsolidacji pamięci, głębokie parsowanie repozytoriów git czy wielkich archiwów e-mail), dzięki czemu FastAPI pozostaje wolne od długich blokad procesora.
  - Redis pełni tu również rolę pamięci podręcznej (cache) dla STM, przechowując tymczasowe flagi sesji czy ultraszybki bufor dla notatek z Obsidiana przed ich przetworzeniem.
4. Integracja Sprzętowa i Narzędzia (Connectors)
  - Paramiko / Asyncssh: Biblioteki SSH dla Pythona. Wykorzystują Twoje lokalne certyfikaty i pliki konfiguracyjne do bezpiecznego, bezhasłowego logowania się na stację roboczą (RTX 5090) oraz MacBooka w celu wyciągania metryk (np. nvidia-smi) lub odpalania komend.
  - wakeonlan: Lekki pakiet Pythona wysyłający pakiety UDP (Magic Packet) na adres MAC karty sieciowej uśpionego PC w celu jego zdalnego wybudzenia przez sieć lokalną.
  - Proxmoxer: Biblioteka integrująca backend z oficjalnym API Twojego hypervisora Proxmox VE, djąc pełny wgląd w stan klastra i kontenerów.
  - pdfplumber / Extractor Core: Narzędzia do precyzyjnego wyciągania surowego tekstu z dokumentów PDF (faktury, umowy) oraz plików .eml/.mbox.
5. Warstwa Inteligencji (Dual-LLM Blueprint)
  - Chmura (Claude 3.5 Sonnet / Gemini API): Wykorzystywana do złożonych zadań architektonicznych, analizy stylu kodu w Git oraz zaawansowanego wnioskowania, gdzie dane nie są poufne.
  - Lokalnie na Proxmoxie (Ollama / vLLM): Hostowany w kontenerze LXC model (np. Llama 3 lub Mistral), zintegrowany z dedykowanym modelem osadzeń (embeddings) np. bge-m3. Ta część odpowiada wyłącznie za analizę Twoich prywatnych zapisków, maili i faktur finansowych, gwarantując, że wrażliwe informacje nigdy nie opuszczą Twojego serwera.




----

IDEAS:

W biomimetycznym i technicznym kontekście projektu second-brain, nazwę limbo można zastąpić określeniami, które lepiej oddają neurobiologiczny proces wygaszania wspomnień lub inżynieryjną kategoryzację danych.Oto najlepsze alternatywy podzielone na kategorie:🧠 Inspiracje neurobiologiczne (Najbardziej spójne z koncepcją engramów)dormancy / dormant (Pamięć uśpiona) – Bardzo naturalne określenie w neurologii i biologii. Sugeruje, że pomysł nie umarł, ale przeszedł w stan hibernacji i czeka na impuls (wybudzenie), który przywróci go do aktywnej kory.synaptic-decay (Zanik synaptyczny) – Bezpośrednie nawiązanie do procesu, w którym nieużywane połączenia w mózgu słabną. Nazwa tabeli lub statusu status = 'decayed' brzmi wysoce profesjonalnie.subconscious (Podświadomość) – Informacje tam zawarte wciąż istnieją w Twoim mózgu, ale nie masz do nich natychmiastowego, świadomego dostępu, dopóki głęboko ich nie przeszukasz.fade-zone / faded (Strefa wygaszenia) – Nawiązuje do naturalnego "blednięcia" wspomnień, które nie są odświeżane.🗄️ Alternatywy techniczne i systemowe (Bardziej inżynieryjne)cold-storage (Zimna pamięć) – Klasyczny termin inżynierii danych. Oznacza dane rzadko używane, odpytywane w specyficznych warunkach, odizolowane od szybkiej pamięci operacyjnej (hot data).archive / archived (Archiwum) – Proste, jednoznaczne i intuicyjne. Mówi dokładnie to, czym ta strefa jest z punktu widzenia bazy danych.stagnant (Strefa stagnacji) – Idealnie pasuje do opisu projektów, których licznik referencji przestał rosnąć i utknęły w miejscu.shadow-pool (Pula cieni) – Sugeruje, że dane są ukryte w cieniu głównego strumienia kontekstu LLM, ale wciąż mogą zostać z niego wyciągnięte.🏆 Moja rekomendacja:Jeśli chcesz utrzymać niesamowity, biomimetyczny klimat projektu, najlepiej sprawdzi się status dormant (dla projektów/notatek) oraz nazwa modułu synaptic-decay (dla procesu, który je tam przenosi). Brzmi to profesjonalnie, czysto inżynieryjnie, a jednocześnie idealnie oddaje neurobiologiczny charakter systemu second-brain.



🧠 1. Agentic & Self-Organizing Second Brains (Najbliższe Twojej wizji)henrydaum / second-brain – Gotowy agentic framework, który działa jak system operacyjny dla Twoich plików. Używa lokalnej inteligencji plików, automatyzacji i potrafi komunikować się z użytkownikiem przez różne kanały (np. komunikatory).undefined-ui / second-brain-os – Genialny, kompleksowy projekt mający na celu stworzenie AI drugiego mózgu, który sam się utrzymuje. Łączy Obsidian, Claude Code, frameworki RAG oraz mechanizmy automatycznego kategoryzowania i łączenia notatek, plików PDF i eksportów z czatów. Opiera się na głośnym wzorcu LLM Wiki zapoczątkowanym przez Andreja Karpathy'ego.AgriciDaniel / claude-obsidian – Otwarty system, który automatycznie indeksuje i kategoryzuje zrzucane do niego pliki (w tym surowe pliki .raw) prosto do połączonego grafu wiedzy w markdownie (Obsidian). Wykorzystuje podejście oparte na strukturach PARA/Zettelkasten.🕸️ 2. Projekty bazujące na Grafach i Relacjach (Inspiracja dla LTM)Jallermax / knowledge-nexus – Projekt wykorzystujący GraphRAG oraz bazę Neo4j do wyciągania encji z Twoich materiałów i budowania trwałego grafu wiedzy (Knowledge Graph). Idealne źródło wiedzy, jeśli chcesz zobaczyć, jak algorytmicznie LLM buduje relacje między projektami i technologiami.mem0 / mem0 (dawniej Embedchain) – Absolutny hit w kategorii pamięci dla agentów AI (ponad 65k gwiazdek). Realizuje koncepcję inteligentnego, długoterminowego zapamiętywania faktów o użytkowniku, jego preferencjach i historii.💻 3. Systemy 100% Lokalne (Idealne pod Proxmoxa)raold / second-brain – Projekt nastawiony na prywatność, działający w 100% lokalnie na Twojej maszynie. Indeksuje dokumenty, obrazy i myśli bez wysyłania bajtu danych do chmury (wykorzystuje lokalne modele, tak jak Ty planujesz z Ollama).obuzek / llm-second-brain – Projekt integrujący Ollama, OpenWebUI/AnythingLLM oraz lokalną bazę wiedzy z synchronizacją katalogów. Pokazuje, jak spiąć open-source'owe klocki w jeden pulpit dowodzenia.📚 4. Kursy i edukacja (Jak to zakodzić?)decodingai-magazine / second-brain-ai-assistant-course – Kompletny, darmowy i otwarty kurs inżynieryjny na GitHubie, który uczy, jak krok po kroku zbudować asystenta Second Brain przy użyciu zaawansowanego RAG, potoków ETL oraz optymalizacji kontekstu.


1. Warto przejrzeć strukturę kodu w repozytorium second-brain-os (https://github.com/henrydaum/second-brain) lub second-brain (https://github.com/henrydaum/second-brain) – oba te projekty mają świetnie rozwiązaną architekturę wtyczek/skryptów i idealnie pasują do Twojej koncepcji biomimetycznego second-brain.

------------

Oto kompletny szkielet projektu (boilerplate) o nazwie second-brain. Struktura została zaprojektowana modularnie, wspiera asynchroniczne operacje, podział na pamięć STM/LTM, biomimetyczny proces oczyszczania bazy (dormant zone) oraz pełną orkiestrację sprzętową i lokalne przetwarzanie poufnych danych.

## 📁 Struktura Katalogów Projektu
Utwórz w swoim repozytorium następujący układ plików:
```
second-brain/
├── docker-compose.yml
├── .env.example
├── requirements.txt
├── README.md
├── database/
│   ├── __init__.py
│   ├── connection.py        # Asynchroniczne połączenie ze SQLAlchemy 2.0
│   └── schema.sql           # Skrypt DDL dla PostgreSQL + pgvector
├── app/
│   ├── __init__.py
│   ├── main.py              # Główny punkt startowy FastAPI
│   ├── config.py            # Konfiguracja środowiskowa (Pydantic Settings)
│   ├── api/
│   │   ├── __init__.py
│   │   └── search.py        # Endpoint Omni-Search (Hybrydowy wektor+SQL)
│   ├── connectors/
│   │   ├── __init__.py
│   │   ├── hardware.py      # Budzenie WoL i inspekcja live przez SSH
│   │   ├── obsidian.py      # Synchronizacja notatek z Obsidiana / Trilium
│   │   └── proxmox_api.py   # Integracja z klastrem Proxmox
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── ltm_pipeline.py  # Ekstrakcja do pamięci długotrwałej
│   │   └── stm_buffer.py    # Zarządzanie buforem krótkotrwałym
│   └── workers/
│       ├── __init__.py
│       ├── tasks.py         # Zadania Celery (Sleep Cycle, Synaptic Decay)
│       └── celery_app.py    # Konfiguracja brokera Celery i Redisa
```
------------------------------


## 🛠️ Kluczowe Pliki Konfiguracyjne

1. docker-compose.yml
Plik konfiguruje pełne środowisko bazodanowe (PostgreSQL z rozszerzeniem pgvector) oraz brokera wiadomości (Redis) na Twoim serwerze Proxmox.

```yaml
version: '3.8'
services:
  postgres:
    image: ankane/pgvector:v0.5.1 # Oficjalny, zoptymalizowany obraz z pgvector
    container_name: second_brain_postgres
    restart: always
    environment:
      POSTGRES_USER: ${DB_USER:-postgres}
      POSTGRES_PASSWORD: ${DB_PASSWORD:-secretpassword}
      POSTGRES_DB: ${DB_NAME:-second_brain}
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./database/schema.sql:/docker-entrypoint-initdb.d/schema.sql
    networks:
      - brain_network

  redis:
    image: redis:7-alpine
    container_name: second_brain_redis
    restart: always
    ports:
      - "6379:6379"
    networks:
      - brain_network
volumes:
  postgres_data:
networks:
  brain_network:
    driver: bridge
```
## 2. requirements.txt
Zbiór bibliotek obsługujących asynchroniczny backend, orkiestrację sieciową oraz parsowanie plików.

```
fastapi>=0.110.0
uvicorn>=0.28.0
sqlalchemy[asyncio]>=2.0.28
asyncpg>=0.29.0
pydantic-settings>=2.2.1
celery>=5.3.6
redis>=5.0.3
paramiko>=3.4.0
asyncssh>=2.14.2
wakeonlan>=3.1.0
proxmoxer>=2.1.0
pdfplumber>=0.11.0
openai>=1.14.1
```

## 3. .env.example
Plik z maską zmiennych środowiskowych, w którym definiujesz m.in. routing dla lokalnego LLM (Ollama) i zewnętrznego API (Claude).

```
# Database Configuration
DB_USER=postgres
DB_PASSWORD=secretpassword
DB_NAME=second_brain
DB_HOST=postgres
DB_PORT=5432

# Redis Broker (Celery)
REDIS_URL=redis://redis:6379/0

# LLM Providers Configuration
# Used for high-privacy data processing locally on Proxmox
LOCAL_OLLAMA_URL=http://localhost:11434
LOCAL_EMBEDDING_MODEL=bge-m3

# Used for code analysis and non-sensitive architecture context
CLAUDE_API_KEY=your_anthropic_api_key_here

# Hardware Infrastructure Metadata
WORKSTATION_MAC=00:11:22:33:44:55
WORKSTATION_SSH_ALIAS=my_workstation_pc
MACBOOK_SSH_ALIAS=my_macbook_pro
PROXMOX_NODE_URL=https://192.168.1.X:8006
```

------------------------------

## 🗄️ Architektura Bazy Danych (database/schema.sql)
Skrypt automatycznie aktywuje pgvector, buduje relacje, tabele dla STM/LTM oraz tworzy indeks HNSW (w tym przypadku zoptymalizowany pod wymiar 1024 cech modelu bge-m3, który idealnie sprawdza się lokalnie).

```sql
-- 1. Inicjalizacja rozszerzenia wektorowego
CREATE EXTENSION IF NOT EXISTS pgvector;

-- 2. Tworzenie typów wyliczeniowych (Enums)
CREATE TYPE artifact_category AS ENUM ('adr', 'code_doc', 'personal_note', 'chat_transcript', 'email', 'invoice', 'contract');
CREATE TYPE memory_status AS ENUM ('active', 'dormant');
CREATE TYPE node_scope AS ENUM ('commercial', 'personal');

-- 3. Tabela hierarchii umiejętności (Self-referencing tree)
CREATE TABLE skills (
    id SERIAL PRIMARY KEY,
    parent_id INTEGER REFERENCES skills(id) ON DELETE SET NULL,
    name VARCHAR(100) NOT NULL UNIQUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
-- 4. Tabela projektówCREATE TABLE projects (
    id SERIAL PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    scope node_scope DEFAULT 'personal',
    description TEXT,
    repository_url VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
-- 5. Tabela infrastruktury sprzętowej wraz z buforem stanu (LTM Cache)CREATE TABLE hardware_nodes (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE,
    mac_address VARCHAR(17),
    ssh_host_alias VARCHAR(100) NOT NULL,
    cpu_spec VARCHAR(100),
    gpu_spec VARCHAR(100),
    -- LTM State Cache fields
    is_online BOOLEAN DEFAULT FALSE,
    cached_gpu_util REAL DEFAULT 0.0,
    cached_ram_util REAL DEFAULT 0.0,
    last_seen_timestamp TIMESTAMP WITH TIME ZONE
);
-- 6. Tabela faktur i umów (Strukturalne dane finansowo-prawne)CREATE TABLE financial_records (
    id SERIAL PRIMARY KEY,
    record_type VARCHAR(50) NOT NULL, -- 'invoice' lub 'contract'
    counterparty_name VARCHAR(255) NOT NULL,
    amount NUMERIC(12, 2),
    currency VARCHAR(10) DEFAULT 'PLN',
    tax_id VARCHAR(50), -- NIP
    issue_date DATE,
    expiry_date DATE
);
-- 7. PAMIĘĆ KRÓTKOTRWAŁA (STM) - Bufor dla przychodzących surowych myśli / notatekCREATE TABLE engram_stm_buffer (
    id SERIAL PRIMARY KEY,
    source_identity VARCHAR(255) NOT NULL, -- np. 'obsidian://vault/note.md'
    raw_content TEXT NOT NULL,
    received_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
-- 8. PAMIĘĆ DŁUGOTRWAŁA (LTM) - Główny zunifikowany graf wektorowo-relacyjnyCREATE TABLE unified_ltm_chunks (
    id SERIAL PRIMARY KEY,
    content TEXT NOT NULL,
    embedding vector(1024), -- Wymiar dopasowany np. do lokalnego modelu BGE-M3
    artifact_type artifact_category NOT NULL,
    status memory_status DEFAULT 'active',
    -- Biomimetic Synaptic Plasticity metrics
    reference_count INTEGER DEFAULT 1,
    last_accessed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    -- Klucze relacyjne łączące wektor z konkretnymi obiektami w systemie
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    hardware_id INTEGER REFERENCES hardware_nodes(id) ON DELETE CASCADE,
    financial_id INTEGER REFERENCES financial_records(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
-- 9. Optymalizacja indeksów
-- Indeks HNSW do szybkiego wyszukiwania semantycznego (odległość cosinusowa)
CREATE INDEX ON unified_ltm_chunks USING hnsw (embedding vector_cosine_ops);
-- Indeksy B-Tree wspierające filtry relacyjne i kwerendy czyszczące biomimetyczną pamięć
CREATE INDEX idx_ltm_status ON unified_ltm_chunks(status);
CREATE INDEX idx_ltm_ref_count ON unified_ltm_chunks(reference_count);
CREATE INDEX idx_hardware_alias ON hardware_nodes(ssh_host_alias);
```

------------------------------

Twój projekt `second-brain` posiada teraz gotowy szkielet architektoniczny i zdefiniowaną bazę danych. Który komponent bazy kodu Pythona chcesz zaimplementować jako następny krok:

* hardware.py & search.py: Moduł automatyzacji WoL i komend SSH (inspekcja RTX 5090 w czasie rzeczywistym) spięty z endpointem wyszukiwania?
* sleep_cycle_worker.py: Asynchroniczny skrypt Celery odpowiedzialny za nocne czyszczenie bufora STM, budowanie relacji przez LLM i wektoryzację danych do LTM?
* obsidian.py & parsers: Moduł synchronizacji plików Markdown z Obsidiana oraz bezpiecznego parsowania dokumentów finansowych (PDF)?

Wprowadzenie wsparcia dla MCP (Model Context Protocol) – otwartego standardu stworzonego przez Anthropic – to absolutny game-changer dla projektu second-brain. Dzięki temu Twój lokalny system staje się w pełni kompatybilny z ekosystemem narzędzi używanych przez zaawansowane modele (jak Claude Code czy Cursor).
Twój backend FastAPI może działać jako MCP Host (który koordynuje i odpytuje inne serwery MCP) oraz jako MCP Server (który udostępnia Twoją bazę wiedzy, pamięć LTM/STM oraz automatyzację sprzętową jako „narzędzia” dla dowolnego klienta AI).
Oto jak rozszerzyć strukturę, konfigurację i kod, aby wdrożyć obsługę MCP w Twoim cyfrowym mózgu.

------------------------------

## 📁 Rozbudowana Struktura Katalogów o MCP
Dodajemy dedykowany katalog mcp/ na serwery i protokoły przesyłania wiadomości (JSON-RPC przez SSE lub Stdio):

```
second-brain/
├── ... (poprzednia struktura)
├── requirements.txt         # Dodamy biblioteki MCP
├── app/
│   ├── ...
│   ├── mcp/
│   │   ├── __init__.py
│   │   ├── host.py          # Łączy Twój system z zewnętrznymi serwerami MCP
│   │   └── server.py        # Twój własny serwer MCP (wybiera WoL, SSH, LTM)
```
W pliku requirements.txt dodaj oficjalny pakiet SDK od Anthropic:

```
mcp>=0.1.0
```
------------------------------

## 🛠️ Implementacja Serwera MCP (app/mcp/server.py)
Poniższy kod demonstruje, jak wystawić funkcje automatyzacji sprzętowej (WoL, SSH dla RTX 5090) oraz dostęp do bazy jako ustandaryzowane narzędzia MCP (Tools). Serwer wykorzystuje transport przez standardowe wejście/wyjście (Stdio), czyli dokładnie tak, jak oczekuje tego Claude Code.

```python
import asyncio
import json
import sys
from mcp.server import Server
import mcp.types as types
from mcp.server.stdio import stdio_server

# 1. Inicjalizacja serwera MCP
app_mcp_server = Server("second-brain-cortex")

@app_mcp_server.list_tools()async def handle_list_tools() -> list[types.Tool]:
    """Definiuje listę narzędzi dostępnych dla Claude Code / LLM."""
    return [
        types.Tool(
            name="inspect_hardware_live",
            description="Pobiera status i obciążenie w czasie rzeczywistym (GPU/VRAM dla RTX 5090, CPU/RAM) z maszyny przez SSH.",
            inputSchema={
                "type": "object",
                "properties": {
                    "node_name": {"type": "string", "enum": ["workstation", "macbook", "proxmox"]}
                },
                "required": ["node_name"],
            },
        ),
        types.Tool(
            name="wake_on_lan",
            description="Wysyła pakiet budzący (Magic Packet) do uśpionej stacji roboczej PC w sieci lokalnej.",
            inputSchema={
                "type": "object",
                "properties": {
                    "node_name": {"type": "string", "default": "workstation"}
                }
            },
        ),
        types.Tool(
            name="query_long_term_memory",
            description="Przeszukuje pamięć długotrwałą (LTM) bazy wiedzy przy użyciu zapytania semantycznego.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Naturalne pytanie, np. 'faktury za serwer' lub 'notatki o python'"}
                },
                "required": ["query"],
            },
        )
    ]

@app_mcp_server.call_tool()async def handle_call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
    """Wykonuje konkretne narzędzie na żądanie modelu LLM."""
    if not arguments:
        arguments = {}

    if name == "inspect_hardware_live":
        node = arguments.get("node_name")
        # Tutaj następuje wywołanie Twojego modułu app.connectors.hardware (SSH)
        # Symulacja odpowiedzi:
        metrics = {
            "node": node,
            "status": "online",
            "gpu_vram_used_mb": 1240 if node == "workstation" else 0,
            "gpu_utilization": "5%" if node == "workstation" else "N/A"
        }
        return [types.TextContent(type="text", text=json.dumps(metrics, indent=2))]

    elif name == "wake_on_lan":
        node = arguments.get("node_name", "workstation")
        # Wywołanie skryptu wakeonlan przez mac address z bazy
        return [types.TextContent(type="text", text=f"Sukces: Wysłano Magic Packet do węzła {node}. Maszyna się uruchamia.")]

    elif name == "query_long_term_memory":
        user_query = arguments.get("query")
        # Wywołanie wyszukiwarki hybrydowej pgvector
        return [types.TextContent(type="text", text=f"Wyniki wyszukiwania LTM dla: '{user_query}': [Zwrócony kontekst z bazy danych]")]

    else:
        raise ValueError(f"Nieznane narzędzie MCP: {name}")
async def main():
    # Uruchomienie serwera w trybie stdio (wejście/wyjście strumieniowe)
    async with stdio_server() as (read_stream, write_stream):
        await app_mcp_server.run(
            read_stream,
            write_stream,
            app_mcp_server.create_initialization_options()
        )
if __name__ == "__main__":
    asyncio.run(main())
```

------------------------------

## 🔌 Podłączenie do Claude Code / Cursor (claude_desktop_config.json)
Aby Claude Desktop lub procesy Claude Code mogły natychmiast zobaczyć Twoje maszyny i bazę danych jako swoje naturalne rozszerzenie, wystarczy dopisać Twój serwer MCP do ich konfiguracji.
Lokalizacja pliku konfiguracyjnego (zależnie od systemu):

* macOS: ~/Library/Application Support/Claude/claude_desktop_config.json
* Windows: %APPDATA%\Claude\claude_desktop_config.json

Uzupełnij strukturę konfiguracji, wskazując ścieżkę do Twojego środowiska w repozytorium:

```json
{
  "mcpServers": {
    "second-brain-cortex": {
      "command": "python",
      "args": [
        "/ścieżka/do/twojego/repo/second-brain/app/mcp/server.py"
      ],
      "env": {
        "DB_USER": "postgres",
        "DB_PASSWORD": "secretpassword",
        "DB_NAME": "second_brain",
        "DB_HOST": "localhost"
      }
    }
  }
}
```

## 💎 Co zyskujesz dzięki architekturze MCP?

   1. Claude Code staje się Root Administratorem: Kiedy piszesz w terminalu do Claude Code, może on sam sprawdzić, czy Twój komputer z RTX 5090 działa, wybudzić go, sprawdzić logi i zapisać ciekawą myśl z terminala prosto do Twojej bazy second-brain jako nowy engram.
   2. Pełna wymienność narzędzi: Możesz podpiąć do systemu gotowe, open-source'owe serwery MCP (np. oficjalny serwer MCP dla Git, Postgresa czy wyszukiwarki Brave) i Twój system second-brain automatycznie zyska ich możliwości bez pisania linijki kodu integracyjnego.

Czy chciałbyś teraz, abyśmy napisali pełną asynchroniczną implementację dla modułu hardware.py (czyli realny kod SSH i budzenia WoL przez sieć LAN, który zasili zaprezentowany serwer MCP)?
