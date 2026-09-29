# 🧠 Second Brain: pgvector & MCP Integration Guide

## 1. Installation (Postgres 18 & pgvector)

Perform these steps inside your Proxmox VM or Container (LXC).

### Install Binaries

```bash
# Update repositories
sudo apt update

# Install Postgres 18 and the matching pgvector version
sudo apt install postgresql-18 postgresql-18-pgvector

```

### Configure Network Access

To allow Obsidian or OpenClaw to connect from your local network (`192.168.88.x`):

1. **Edit `postgresql.conf**`:
`sudo nano /etc/postgresql/18/main/postgresql.conf`
Set: `listen_addresses = '*'`
2. **Edit `pg_hba.conf**`:
`sudo nano /etc/postgresql/18/main/pg_hba.conf`
Add at the bottom:
`host  secondbraindb  midy  192.168.88.0/24  scram-sha-256`
3. **Restart**:
`sudo systemctl restart postgresql`

---

## 2. Database & User Setup

Log into Postgres as the superuser to initialize the environment.

```sql
-- 1. Create the database
CREATE DATABASE secondbraindb;

-- 2. Create the specialized role
CREATE USER midy WITH PASSWORD 'your_secure_password';

-- 3. Connect to the new DB
\c secondbraindb

-- 4. Enable pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- 5. Grant Permissions
GRANT ALL PRIVILEGES ON DATABASE secondbraindb TO midy;
GRANT ALL ON SCHEMA public TO midy;

```

---

## 3. Schema Design (Unified Memory)

This table stores **Obsidian notes**, **Trilium exports**, and **Agent chats** in one place for cross-contextual retrieval.

```sql
CREATE TABLE agent_memories (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    category text,          -- 'note', 'chat', 'idea'
    agent_name text,        -- 'System', 'OpenClaw', 'Claude'
    source_file text,       -- File path or Chat ID
    content text,           -- The actual text
    embedding vector(384),  -- 384 for all-MiniLM-L6-v2 (standard/fast)
    metadata jsonb,         -- YAML frontmatter or timestamps
    created_at timestamptz DEFAULT now()
);

-- HNSW Index for millisecond search speeds on your Asus Sabertooth
CREATE INDEX ON agent_memories USING hnsw (embedding vector_cosine_ops);

```

---

## 4. Connecting Obsidian

Since Obsidian is local files, we use a **"Push"** script. This script watches your vault and updates Postgres in real-time.

1. **Install Python requirements**:
`pip install "psycopg[binary]" pgvector sentence-transformers watchdog`
2. **Run the Sync Script**:
Create `sync.py` to watch your vault folder. Every time you save a `.md` file, the script chunks the text, creates vectors, and updates the `agent_memories` table with `category='note'`.

---

## 5. Connecting OpenClaw via MCP

To give OpenClaw "Long-Term Memory," we use the **Model Context Protocol**.

### The Architecture

Instead of OpenClaw talking directly to SQL, it talks to an **MCP Server**. This server provides "Tools" like `search_memory` or `save_thought`.

### Implementation Steps

1. **Download an MCP Postgres Server**:
Use a pre-built server like `@modelcontextprotocol/server-postgres`.
2. **Configure OpenClaw (`mcp_config.json`)**:
Add the server to your agent's configuration:
```json
{
  "mcpServers": {
    "second-brain": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-postgres", "postgresql://midy:password@192.168.88.231/secondbraindb"]
    }
  }
}

```


3. **Agent Interaction**:
You can now say to OpenClaw: *"Search my memories for my SATA port configuration."*
The agent will use the MCP tool to run a vector search:
`SELECT content FROM agent_memories ORDER BY embedding <=> [query_vector] LIMIT 3;`

---

## 6. Proxmox Optimization (Asus Sabertooth Mark 2)

* **CPU**: Set the VM CPU type to **"Host"**. This allows the embedding models to use **AVX2 instructions**, making vector generation 3x faster.
* **Storage**: Ensure the Postgres data partition is on an **SSD**. Vector indexing (HNSW) is I/O intensive.
* **Memory**: Allocate at least **4GB RAM**. Postgres 18 uses more memory for parallel workers, which speeds up index building.

## Commit messages

Conventional Commits: `type(scope): summary`. The header is imperative, ≤ 50 characters
(72 is the hard limit) and has no period. An optional body explains what and why, wrapped at
72. The optional footer holds `BREAKING CHANGE:` / `Closes #n`. AI attribution
(`Co-Authored-By`, "Generated with Claude") is never allowed. The `commit-msg` hook in
`.githooks/` enforces this. `just install` enables it (`just hooks` on its own).
